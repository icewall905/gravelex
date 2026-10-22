/*
 * HA Health Sync: samples Pebble Health on the watch, hands the values to the JS
 * component running inside the phone's Pebble app, which POSTs them to the
 * self-hosted bridge. Re-launches itself periodically via the wakeup service.
 */
#include <pebble.h>

#define SYNC_INTERVAL_SECONDS (60 * 60)
#define WAKEUP_COOKIE 0x48415348
#define EXIT_TIMEOUT_MS 12000
#define EXIT_AFTER_SYNC_MS 2500
#define PERSIST_KEY_LAST_SYNC 1

static Window *s_window;
static TextLayer *s_status_layer;
static AppTimer *s_exit_timer;
static bool s_launched_by_wakeup;
static int s_send_attempts;

#define MAX_SEND_ATTEMPTS 4
#define RETRY_DELAY_MS 3000

static void send_health_data(void);
static void retry_send(void *data);

static void set_status(const char *text) {
  if (s_status_layer) {
    text_layer_set_text(s_status_layer, text);
  }
}

static HealthValue sum_today_or_zero(HealthMetric metric) {
  // Metrics vary by platform (no HR on some), so check before reading.
  HealthServiceAccessibilityMask mask =
      health_service_metric_accessible(metric, time_start_of_today(), time(NULL));
  if (mask & HealthServiceAccessibilityMaskAvailable) {
    return health_service_sum_today(metric);
  }
  return 0;
}

/*
 * Pebble Fit records walks/runs/workouts as health "activities" (sessions), which are
 * separate from the daily metric totals. Collect today's ones so HA can show the last
 * session plus a per-day workout tally.
 */
#define ACTIVITY_MASK (HealthActivityWalk | HealthActivityRun | HealthActivityOpenWorkout)

typedef struct {
  int32_t count;
  int32_t total_seconds;
  int32_t last_type;
  int32_t last_start;
  int32_t last_seconds;
} ActivitySummary;

static int32_t activity_type_code(HealthActivity activity) {
  // Small stable codes; the bridge maps these to names.
  switch (activity) {
    case HealthActivityWalk: return 1;
    case HealthActivityRun: return 2;
    case HealthActivityOpenWorkout: return 3;
    default: return 0;
  }
}

static bool activity_iter_cb(HealthActivity activity, time_t time_start, time_t time_end,
                             void *context) {
  ActivitySummary *summary = (ActivitySummary *)context;
  int32_t seconds = (int32_t)(time_end - time_start);
  if (seconds <= 0) {
    return true;
  }
  summary->count++;
  summary->total_seconds += seconds;
  // Iterating into the past, so the first callback is the most recent session.
  if (summary->last_start == 0) {
    summary->last_type = activity_type_code(activity);
    summary->last_start = (int32_t)time_start;
    summary->last_seconds = seconds;
  }
  return true;
}

static void collect_activities(ActivitySummary *summary) {
  memset(summary, 0, sizeof(*summary));
  time_t start = time_start_of_today();
  time_t now = time(NULL);
  HealthServiceAccessibilityMask mask =
      health_service_any_activity_accessible(ACTIVITY_MASK, start, now);
  if (!(mask & HealthServiceAccessibilityMaskAvailable)) {
    APP_LOG(APP_LOG_LEVEL_INFO, "no activity data accessible today");
    return;
  }
  health_service_activities_iterate(ACTIVITY_MASK, start, now, HealthIterationDirectionPast,
                                    activity_iter_cb, summary);
}

static void schedule_next_wakeup(void) {
  wakeup_cancel_all();
  time_t next = time(NULL) + SYNC_INTERVAL_SECONDS;
  WakeupId id = wakeup_schedule(next, WAKEUP_COOKIE, false);
  if (id < 0) {
    // Slot taken or time in the past; retry a minute later rather than giving up.
    wakeup_schedule(time(NULL) + SYNC_INTERVAL_SECONDS + 60, WAKEUP_COOKIE, false);
  }
}

static void exit_now(void *data) {
  s_exit_timer = NULL;
  // Emptying the window stack ends the app, returning to the watchface. Done for
  // manual launches too, so a sync never leaves the app sitting on screen.
  window_stack_pop_all(false);
}

static void arm_exit_timer_ms(uint32_t delay_ms) {
  if (s_exit_timer) {
    app_timer_cancel(s_exit_timer);
  }
  s_exit_timer = app_timer_register(delay_ms, exit_now, NULL);
}

static void arm_exit_timer(void) {
  arm_exit_timer_ms(EXIT_TIMEOUT_MS);
}

static void send_health_data(void) {
  s_send_attempts++;
  DictionaryIterator *iter;
  AppMessageResult result = app_message_outbox_begin(&iter);
  if (result != APP_MSG_OK) {
    APP_LOG(APP_LOG_LEVEL_ERROR, "outbox_begin failed: %d", result);
    if (s_send_attempts < MAX_SEND_ATTEMPTS) {
      set_status("Retrying...");
      app_timer_register(RETRY_DELAY_MS, retry_send, NULL);
      return;
    }
    set_status("Phone not ready");
    arm_exit_timer();
    return;
  }

  int32_t steps = (int32_t)sum_today_or_zero(HealthMetricStepCount);
  int32_t active_seconds = (int32_t)sum_today_or_zero(HealthMetricActiveSeconds);
  int32_t distance_meters = (int32_t)sum_today_or_zero(HealthMetricWalkedDistanceMeters);
  int32_t active_kcal = (int32_t)sum_today_or_zero(HealthMetricActiveKCalories);
  int32_t resting_kcal = (int32_t)sum_today_or_zero(HealthMetricRestingKCalories);
  int32_t sleep_seconds = (int32_t)sum_today_or_zero(HealthMetricSleepSeconds);
  int32_t sleep_restful_seconds = (int32_t)sum_today_or_zero(HealthMetricSleepRestfulSeconds);
  int32_t ts = (int32_t)time(NULL);

  int32_t heart_rate_bpm = 0;
  HealthServiceAccessibilityMask hr_mask =
      health_service_metric_accessible(HealthMetricHeartRateBPM, time(NULL) - 3600, time(NULL));
  if (hr_mask & HealthServiceAccessibilityMaskAvailable) {
    heart_rate_bpm = (int32_t)health_service_peek_current_value(HealthMetricHeartRateBPM);
  }

  ActivitySummary activities;
  collect_activities(&activities);

  BatteryChargeState battery = battery_state_service_peek();
  int32_t battery_percent = (int32_t)battery.charge_percent;
  int32_t battery_charging = battery.is_charging ? 1 : 0;

  dict_write_int(iter, MESSAGE_KEY_steps, &steps, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_active_seconds, &active_seconds, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_distance_meters, &distance_meters, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_active_kcal, &active_kcal, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_resting_kcal, &resting_kcal, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_sleep_seconds, &sleep_seconds, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_sleep_restful_seconds, &sleep_restful_seconds, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_heart_rate_bpm, &heart_rate_bpm, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_battery_percent, &battery_percent, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_battery_charging, &battery_charging, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_ts, &ts, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_activity_count, &activities.count, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_activity_seconds, &activities.total_seconds, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_last_activity_type, &activities.last_type, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_last_activity_start, &activities.last_start, sizeof(int32_t), true);
  dict_write_int(iter, MESSAGE_KEY_last_activity_seconds, &activities.last_seconds, sizeof(int32_t), true);

  result = app_message_outbox_send();
  APP_LOG(APP_LOG_LEVEL_INFO, "sent steps=%d hr=%d sleep_s=%d batt=%d acts=%d act_s=%d",
          (int)steps, (int)heart_rate_bpm, (int)sleep_seconds, (int)battery_percent,
          (int)activities.count, (int)activities.total_seconds);
  set_status(result == APP_MSG_OK ? "Syncing..." : "Send failed");
  arm_exit_timer();
}

static void inbox_received(DictionaryIterator *iter, void *context) {
  Tuple *ack = dict_find(iter, MESSAGE_KEY_ack);
  if (!ack) {
    return;
  }
  // JS reports the HTTP outcome: 1 = the bridge accepted the payload.
  if (ack->value->int32 == 1) {
    persist_write_int(PERSIST_KEY_LAST_SYNC, (int)time(NULL));
    set_status("Synced");
    // Show the result briefly, then get out of the way.
    arm_exit_timer_ms(EXIT_AFTER_SYNC_MS);
    return;
  }
  set_status("Bridge error");
  arm_exit_timer();
}

static void retry_send(void *data) {
  send_health_data();
}

static void outbox_failed(DictionaryIterator *iter, AppMessageResult reason, void *context) {
  APP_LOG(APP_LOG_LEVEL_ERROR, "outbox failed: %d (attempt %d)", reason, s_send_attempts);
  // PebbleKit JS can take a few seconds to start, so retry before giving up.
  if (s_send_attempts < MAX_SEND_ATTEMPTS) {
    set_status("Retrying...");
    app_timer_register(RETRY_DELAY_MS, retry_send, NULL);
    return;
  }
  set_status("Phone unreachable");
  arm_exit_timer();
}

static void js_ready(void *data) {
  send_health_data();
}

static void window_load(Window *window) {
  Layer *root = window_get_root_layer(window);
  GRect bounds = layer_get_bounds(root);
  s_status_layer = text_layer_create(GRect(0, bounds.size.h / 2 - 20, bounds.size.w, 40));
  text_layer_set_text_alignment(s_status_layer, GTextAlignmentCenter);
  text_layer_set_font(s_status_layer, fonts_get_system_font(FONT_KEY_GOTHIC_24_BOLD));
  text_layer_set_text(s_status_layer, "Reading health");
  layer_add_child(root, text_layer_get_layer(s_status_layer));
}

static void window_unload(Window *window) {
  text_layer_destroy(s_status_layer);
  s_status_layer = NULL;
}

static void init(void) {
  s_launched_by_wakeup = (launch_reason() == APP_LAUNCH_WAKEUP);
  APP_LOG(APP_LOG_LEVEL_INFO, "launched by %s", s_launched_by_wakeup ? "wakeup" : "user");

  app_message_register_inbox_received(inbox_received);
  app_message_register_outbox_failed(outbox_failed);
  app_message_open(512, 256);

  s_window = window_create();
  window_set_window_handlers(s_window, (WindowHandlers){
      .load = window_load,
      .unload = window_unload,
  });
  window_stack_push(s_window, false);

  schedule_next_wakeup();

  // Give PebbleKit JS a moment to spin up before the first outbox attempt.
  app_timer_register(1500, js_ready, NULL);
}

static void deinit(void) {
  window_destroy(s_window);
}

int main(void) {
  init();
  app_event_loop();
  deinit();
  return 0;
}
