/*
 * Runs inside the phone's Pebble app. Forwards the watch's health/battery report
 * to the paired Pebble Health receiver using a scoped runtime token.
 */
var ENDPOINT = 'https://pebble-health.example.lan/health';
var PAIR = 'https://pebble-health.example.lan/pair?kind=history';
var TOKEN_KEY = 'pebble_health_history_token';
var AUTH_TOKEN = localStorage.getItem(TOKEN_KEY) || '';

// Keys the watch sends that map 1:1 onto the integration's status fields.
var STATUS_KEYS = [
  'steps', 'active_seconds', 'distance_meters', 'active_kcal', 'resting_kcal',
  'sleep_seconds', 'sleep_restful_seconds', 'heart_rate_bpm', 'battery_percent'
];

function ack(ok) {
  Pebble.sendAppMessage({ ack: ok ? 1 : 0 });
}

Pebble.addEventListener('appmessage', function (e) {
  var d = e.payload;
  var status = {};
  for (var i = 0; i < STATUS_KEYS.length; i++) {
    var k = STATUS_KEYS[i];
    if (typeof d[k] === 'number') {
      status[k] = d[k];
    }
  }
  // A heart rate of 0 means "no reading", not a real measurement.
  if (status.heart_rate_bpm === 0) {
    delete status.heart_rate_bpm;
  }
  if (typeof d.battery_charging === 'number') {
    status.battery_charging = d.battery_charging === 1;
  }

  // Activity sessions ride outside `status`: the HA integration only knows the
  // fields above, so these go top-level for the bridge's MQTT sensors.
  var ACTIVITY_TYPES = { 1: 'walk', 2: 'run', 3: 'workout' };
  var activity = {
    count_today: typeof d.activity_count === 'number' ? d.activity_count : 0,
    seconds_today: typeof d.activity_seconds === 'number' ? d.activity_seconds : 0
  };
  if (d.last_activity_start) {
    activity.last = {
      type: ACTIVITY_TYPES[d.last_activity_type] || 'unknown',
      start: d.last_activity_start,
      seconds: d.last_activity_seconds || 0
    };
  }

  if (!AUTH_TOKEN) { ack(false); return; }
  var req = new XMLHttpRequest();
  req.open('POST', ENDPOINT, true);
  req.setRequestHeader('Content-Type', 'application/json');
  req.setRequestHeader('Authorization', 'Bearer ' + AUTH_TOKEN);
  req.timeout = 15000;
  req.onload = function () {
    console.log('bridge responded ' + req.status);
    ack(req.status >= 200 && req.status < 300);
  };
  req.onerror = function () {
    console.log('bridge request failed');
    ack(false);
  };
  req.ontimeout = function () {
    console.log('bridge request timed out');
    ack(false);
  };
  req.send(JSON.stringify({ ts: d.ts, source: 'watchapp', status: status, activity: activity }));
});

Pebble.addEventListener('ready', function () {
  console.log('HA Health Sync JS ready');
});

Pebble.addEventListener('showConfiguration', function () {
  Pebble.openURL(PAIR);
});

Pebble.addEventListener('webviewclosed', function (e) {
  if (!e.response || e.response === 'CANCELLED') return;
  try {
    var data = JSON.parse(decodeURIComponent(e.response));
    if (typeof data.token !== 'string' || !data.token) return;
    AUTH_TOKEN = data.token;
    localStorage.setItem(TOKEN_KEY, AUTH_TOKEN);
  } catch (err) {
    ack(false);
  }
});
