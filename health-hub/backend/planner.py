"""Account-scoped planned workouts. Completed activities stay in the training ledger."""
import json
import os
import re
import uuid
from contextlib import closing
from datetime import UTC, date, datetime, time, timedelta
from time import monotonic
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Blueprint, Response, request

import accounts
import activity_review
import fitness
import planner_context
import planner_ntfy
import training
import workout_edits


class Conflict(ValueError):
    pass


def text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError("Check the required fields and text lengths.")
    return value.strip()


def clock(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}", value):
        raise ValueError("Enter a time in HH:MM format.")
    time.fromisoformat(value)
    return value


def session(data, zone, ident=None):
    if not isinstance(data, dict):
        raise ValueError("Invalid workout.")
    raw_start = data.get("start", "")
    if not isinstance(raw_start, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}", raw_start):
        raise ValueError("Enter a local calendar date and time.")
    start = datetime.fromisoformat(raw_start)
    if start.tzinfo or start.second or start.microsecond or start.year not in range(2000, 2100):
        raise ValueError("Enter a local calendar date and time.")
    # A skipped civil time must be corrected before it can be put on a calendar.
    if start.replace(tzinfo=zone).astimezone(UTC).astimezone(zone).replace(tzinfo=None) != start:
        raise ValueError("That time does not exist in the calendar timezone.")
    minutes = data.get("minutes")
    if type(minutes) is not int or not 1 <= minutes <= 720:
        raise ValueError("Duration must be between 1 and 720 minutes.")
    status = data.get("status", "planned")
    if status not in ("planned", "done", "skipped", "rescheduled"):
        raise ValueError("Choose a workout status.")
    return {"id": ident or uuid.uuid4().hex, "title": text(data.get("title"), 120, True),
            "status": status,
            "start": start.isoformat(timespec="minutes"), "minutes": minutes,
            "details": text(data.get("details", ""), 4000)}


def read(db):
    db.execute("CREATE TABLE IF NOT EXISTS workout_planner (id INTEGER PRIMARY KEY, state TEXT NOT NULL)")
    row = db.execute("SELECT state FROM workout_planner WHERE id=1").fetchone()
    return json.loads(row[0]) if row else {
        "revision": 0, "timezone": str(fitness.TZ), "priorities": "", "activities": "",
        "goals": "", "availability": "", "morning": "", "follow_up": False,
        "workouts": [], "messages": [], "options": [],
    }


def update(body, change):
    with closing(fitness.connect()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        state = read(db)
        if body.get("revision") != state["revision"]:
            raise Conflict("The planner changed. Refresh and try again.")
        change(state)
        if body.get("action") == "chat":
            planner_context.archive(db, state["messages"][:-2])
            planner_context.append(db, state["messages"][-2:], datetime.now(UTC).isoformat())
        state["workouts"].sort(key=lambda workout: workout["start"])
        if len(state["workouts"]) > 1500:
            raise ValueError("The calendar has reached its workout limit.")
        state["revision"] += 1
        db.execute("INSERT OR REPLACE INTO workout_planner VALUES (1, ?)", (json.dumps(state),))
    return state


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def trainer_ready():
    return bool(os.environ.get("PH_TRAINER_WEBHOOK") and os.environ.get("PH_TRAINER_SECRET"))


def trainer(state, message, context, reschedule=False, synthetic=False):
    url = os.environ["PH_TRAINER_WEBHOOK"]
    destination = urlsplit(url)
    if destination.scheme != "https" or not destination.hostname or destination.username:
        raise ValueError("Trainer webhook configuration is invalid.")
    summary = {} if synthetic else fitness.summary(42)
    # Use aggregate training and recovery signals. Sample streams and device
    # metadata add cost and have no role in generating a schedule.
    workout_fields = ("kind", "start", "seconds", "rpe", "load", "load_hr", "load_rpe",
                      "distance_m", "hr_avg", "avg_hr", "max_hr", "hr_load", "rpe_load", "hr_coverage", "excluded")
    day_fields = ("date", "steps", "sleep_seconds", "resting_hr", "rhr", "active_seconds",
                  "hrv", "readiness", "weight_kg", "load", "status", "minutes", "active_minutes",
                  "step_minutes", "hr_minutes", "distance_m", "hr_avg")
    def select(rows, fields):
        return [{key: row[key] for key in fields if key in row} for row in rows]
    recovery = summary.get("recovery", {})
    has_activity = [row for row in summary.get("daily", []) if row.get("minutes")]
    daytime = summary.get("daytime_stress") or {}
    oxygen = summary.get("oxygen") or {}
    weight = summary.get("weight") or {}
    ledger = summary.get("training_ledger") or {}

    def workout_preview(item):
        return {**item, "details": item.get("details", "")[:260]}
    memory = state.get("_recall", {})
    settings = state.get("model_settings", planner_context.defaults())
    search_allowed = settings["web_search"] and bool(os.environ.get("PH_TRAINER_SEARCH_URL"))

    today = datetime.now(ZoneInfo(state["timezone"])).date()
    cutoff = str(today - timedelta(days=14))
    payload = {
        "model_settings": {key:settings[key] for key in ("base_url", "model")},
        "web_search_allowed": search_allowed,
        "history_search_allowed": bool(memory),
        "saved_notes": state.get("notes", [])[-20:],
        **memory,
        "message": message, "workout_context": context,
        "operation": "reschedule_selected_workout" if reschedule else "consult",
        "today": str(today),
        "setup": {key: state[key] for key in ("timezone", "priorities", "activities", "goals", "availability")},
        "calendar": [workout_preview(item) for item in state["workouts"] if item["start"][:10] >= cutoff][:75],
        "conversation": [] if memory else state["messages"][-8:],
        "previous_options": [{**option, "workouts":[workout_preview(item) for item in option["workouts"][:24]]}
                             for option in state["options"]],
        "health": {
            "workouts": select(summary.get("workouts", [])[-80:], workout_fields),
            "daily": select(has_activity[-42:], day_fields),
            "training": select(summary.get("history", [])[-42:], day_fields + (
                "acute", "chronic", "freshness", "ratio", "coverage", "confirmed", "acwr",
            )),
            "recovery": {
                "sleep_nights": select(recovery.get("sleep_nights", [])[-21:], (
                    "date", "night", "sleep_s", "restful_s", "source", "resting_hr", "start", "end",
                )),
                "readiness": recovery.get("readiness"), "hrv_status": recovery.get("hrv_status"),
                "readiness_history": recovery.get("readiness_history", [])[-21:],
            },
            "weight_trend": {key:weight.get(key) for key in ("latest", "change_7d_kg", "change_28d_kg")},
            "fitness": summary.get("fitness"), "profile": summary.get("profile"),
            "stress_estimate": {key:daytime.get(key) for key in ("score","status","method","estimated")},
            "oxygen": {key:oxygen.get(key) for key in ("status","latest")},
            "training_ledger": {key:ledger.get(key) for key in (
                "status", "as_of", "baseline_end", "required_days", "confirmed_consecutive_days", "confirmed_days",
            )},
        },
    }
    opener = build_opener(NoRedirect())
    deadline = monotonic() + 85
    searched = False
    for attempt in range(3):
        if attempt and not searched:
            payload["validation_feedback"] = (
                "Return a valid JSON object with actionable options matching the operation. "
                "For a reschedule, include exactly one session per option and change the selected start time."
            )
        req = Request(url, json.dumps(payload).encode(), {
            "Content-Type": "application/json", "X-Pebble-Trainer": os.environ["PH_TRAINER_SECRET"],
        })
        try:
            with opener.open(req, timeout=min(45, max(1, deadline - monotonic()))) as response:
                result = json.loads(response.read(180_000))
            web_query = result.get("search_query") if search_allowed else None
            history_query = result.get("history_query") if memory else None
            if (web_query or history_query) and not searched and attempt < 2 and monotonic() < deadline - 12:
                if web_query:
                    try:
                        payload["web_results"] = planner_context.search(text(web_query, 160))
                    except (OSError, ValueError, TypeError, KeyError):
                        payload["web_results"] = []
                if history_query:
                    with closing(fitness.connect()) as db:
                        lookup = planner_context.recall(db, text(history_query, 200))
                    payload["history_search_results"] = lookup["relevant_older_messages"]
                payload.update(web_search_allowed=False, history_search_allowed=False)
                searched = True
                continue
            reply, options = parse_proposals(state, result, context, reschedule, today)
            notes = result.get("memory_notes", [])
            notes = [item.strip() for item in notes[:3] if isinstance(item, str) and 0 < len(item.strip()) <= 400] if isinstance(notes, list) else []
            return reply, options, notes
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            if attempt >= 1 or monotonic() >= deadline - 1:
                raise


def parse_proposals(state, result, context, reschedule, today):
    zone = ZoneInfo(state["timezone"])
    reply = text(result["reply"], 6000, True)
    options = result.get("options", [])
    if not isinstance(options, list) or len(options) > 3 or (reschedule and not options):
        raise ValueError("Invalid Trainer options.")
    existing = {item["id"] for item in state["workouts"]}
    parsed = []
    for option in options:
        workouts = option.get("workouts", [])
        # The UI explicitly requested a replacement of this one workout.
        # Derive the removal from that selection, independently of model IDs.
        remove = [context["id"]] if reschedule else option.get("remove_ids", [])
        if (not isinstance(workouts, list) or len(workouts) > 60
                or not isinstance(remove, list) or not set(remove) <= existing
                or (not workouts and (reschedule or not remove))):
            raise ValueError("Invalid Trainer proposal.")
        planned = [session(dict(item, status="planned"), zone) for item in workouts]
        past = any(date.fromisoformat(item["start"][:10]) < today for item in planned)
        if reschedule:
            # An unchanged alternative must not discard other valid dates.
            if len(planned) != 1 or planned[0]["start"] == context["start"] or past:
                continue
        elif past:
            raise ValueError("Trainer proposed a workout in the past.")
        parsed.append({"id": uuid.uuid4().hex, "title": text(option["title"], 120, True),
                       "summary": text(option.get("summary", ""), 2000), "workouts": planned,
                       "remove_ids": remove, "reschedule": reschedule})
    if reschedule and not parsed:
        raise ValueError("Trainer did not propose a new time for the selected workout.")
    return reply, parsed


def moments(item, state):
    zone = ZoneInfo(state["timezone"])
    start = datetime.fromisoformat(item["start"]).replace(tzinfo=zone).astimezone(UTC)
    return start, start + timedelta(minutes=item["minutes"])


def reminders(state, today):
    zone = ZoneInfo(state["timezone"])
    for item in state["workouts"]:
        if item.get("status") in ("skipped", "rescheduled"):
            continue
        start, end = moments(item, state)
        day = start.astimezone(zone).date()
        if state["morning"] and day == today and item.get("status") != "done":
            morning = datetime.combine(day, time.fromisoformat(state["morning"]), zone).astimezone(UTC)
            if morning <= start:
                yield item, "morning", morning
        follow_up = end + timedelta(minutes=60)
        if state["follow_up"] and follow_up.astimezone(zone).date() == today:
            yield item, "follow-up", follow_up


def calendar(state):
    def escape(value):
        return (value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n")
                .replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,"))

    def stamp(value):
        return value.strftime("%Y%m%dT%H%M%SZ")

    def fold(line):
        parts = []
        part = ""
        for char in line:
            if len((part + char).encode()) > 75:
                parts.append(part)
                part = " "
            part += char
        return "\r\n".join(parts + [part])

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Pebble Health//Workout Planner//EN"]
    now = stamp(datetime.now(UTC))
    for item in state["workouts"]:
        start, end = moments(item, state)
        lines += ["BEGIN:VEVENT", f"UID:{item['id']}@pebble-health",
                  f"DTSTAMP:{now}", f"SEQUENCE:{state['revision']}", f"DTSTART:{stamp(start)}",
                  f"DTEND:{stamp(end)}", f"SUMMARY:{escape(item['title'])}",
                  f"DESCRIPTION:{escape(item['details'])}",
                  "STATUS:CANCELLED" if item.get("status") in ("skipped", "rescheduled") else "STATUS:CONFIRMED",
                  "END:VEVENT"]
    return "\r\n".join(map(fold, lines + ["END:VCALENDAR", ""]))


def blueprint():
    bp = Blueprint("planner", __name__)

    def current():
        with closing(fitness.connect()) as db:
            return read(db)

    @bp.get("/api/planner")
    def get():
        state = current()
        for item in state["workouts"]:
            start, end = moments(item, state)
            item.update(start_ms=int(start.timestamp() * 1000), end_ms=int(end.timestamp() * 1000))
        return dict(state, trainer_ready=trainer_ready(),
                    model_settings=state.get("model_settings", planner_context.defaults()),
                    allowed_model_endpoints=planner_context.allowed_endpoints(),
                    search_available=bool(os.environ.get("PH_TRAINER_SEARCH_URL")),
                    notes=state.get("notes", []), ntfy=planner_ntfy.settings(state))

    @bp.get("/api/planner/history")
    def history():
        month = request.args.get("month", "")
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", month):
            return {"error": "Choose a valid month."}, 400
        try:
            first = date.fromisoformat(month + "-01")
            last = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
        except (ValueError, OverflowError):
            return {"error": "Choose a valid month."}, 400
        with closing(fitness.connect()) as db:
            state = read(db)
            zone = ZoneInfo(state["timezone"])
            lo = datetime.combine(first, time.min, zone).timestamp()
            hi = datetime.combine(last, time.min, zone).timestamp()
            metrics = fitness.phone_workout_metrics(db)
            rows = workout_edits.effective_rows(db)
            duplicates = training.superseded(rows)
            recorded = [
                {**{key: row.get(key) for key in ("id", "kind", "seconds", "source", "rpe")},
                 "start": datetime.fromtimestamp(row["start"], zone).isoformat(timespec="minutes")[:16],
                 "metrics": {key: value for key, value in metrics.get(row["id"], {}).items()
                             if key in ("distance_m", "avg_hr", "max_hr", "notes", "calories", "ascent_m")}}
                for row in rows
                if lo <= row["start"] < hi and not row.get("ignored") and row["id"] not in duplicates
            ]
        return {"workouts": recorded}

    @bp.get("/api/planner/reminders")
    def due():
        state = current()
        now = datetime.now(UTC)
        today = now.astimezone(ZoneInfo(state["timezone"])).date()
        delivery = planner_ntfy.settings(state)
        if delivery["available"] and delivery["enabled"]:
            return {"account":accounts.current()["id"], "reminders":[]}
        return {"account": accounts.current()["id"], "reminders": [
            {"id": item["id"], "kind": kind, "at": int(at.timestamp())}
            for item, kind, at in reminders(state, today)
            if at <= now < at + timedelta(hours=3)
        ]}

    @bp.post("/api/planner/check-in")
    def check_in():
        request.max_content_length = 4096
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return {"error": "Provide goal progress."}, 400
        if not trainer_ready():
            return {"error": "Trainer is unavailable."}, 503

        bounds = {"minute": (0, 1439), "steps": (0, 200000), "step_goal": (1, 50000),
                  "weekly_minutes": (0, 20000), "weekly_goal": (1, 20000)}
        progress = {}
        for key, (low, high) in bounds.items():
            value = body.get(key)
            if value is None and key in ("steps", "weekly_minutes"):
                continue
            if type(value) not in (int, float) or not low <= value <= high:
                return {"error": "Invalid goal progress."}, 400
            progress[key] = value
        if not ("steps" in progress or "weekly_minutes" in progress):
            return {"error": "Goal progress is unavailable."}, 400
        progress["move_behind"] = body.get("move_behind") is True and "steps" in progress

        saved = current()
        model = saved.get("model_settings", planner_context.defaults())
        state = {"timezone": saved["timezone"], "workouts": [], "messages": [], "options": [],
                 "priorities": "", "activities": "", "goals": "", "availability": "",
                 "model_settings": dict(model, web_search=False)}
        prompt = (
            "Write a friendly phone check-in using only the goal progress in workout_context. "
            "Write one plain sentence, at most 150 characters, with one gentle next step or celebrate a goal met. "
            "The app displays the numbers separately, so don't repeat them. Weekly minutes use a rolling seven-day window. "
            "Only say steps are behind pace if move_behind is true. Missing progress is unknown. "
            "Do not prescribe strenuous exercise or medical advice. Return an empty options array."
        )
        try:
            reply, _, _ = trainer(state, prompt, progress, synthetic=True)
            if len(reply) > 180 or "\n" in reply or "\r" in reply:
                raise ValueError("Invalid check-in")
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return {"error": "Trainer could not write a check-in."}, 502
        return {"message": reply}

    @bp.post("/api/planner/activity-review")
    def review_activity():
        request.max_content_length = 512_000
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return {"error": "Provide activity details."}, 400
        if not trainer_ready():
            return {"error": "Trainer is unavailable."}, 503
        try:
            if "id" in body:
                ident = text(body["id"], 250, True)
                with closing(fitness.connect()) as db:
                    workout = next((row for row in workout_edits.effective_rows(db) if row["id"] == ident), None)
                    if workout is None:
                        return {"error": "Activity not found."}, 404
                    phone = db.execute("SELECT payload FROM phone_workouts WHERE id=?", (ident,)).fetchone()                         if ident.startswith("phone:") else None
                    evidence = activity_review.from_hub(db, workout, json.loads(phone["payload"]) if phone else None)
            else:
                evidence = activity_review.from_phone(body, fitness.PHONE_SPORTS)
        except (ValueError, TypeError) as error:
            return {"error": str(error)}, 400

        saved = current()
        settings = saved.get("model_settings", planner_context.defaults())
        state = {"timezone": saved["timezone"], "workouts": [], "messages": [], "options": [],
                 "priorities": "", "activities": "", "goals": "", "availability": "",
                 "model_settings": dict(settings, web_search=False)}
        try:
            reply, _, _ = trainer(state, activity_review.PROMPT, evidence, synthetic=True)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            return {"error": "Trainer could not complete this activity review. Try again."}, 502
        return {"reply": activity_review.verified_timing(evidence) + "\n\n" + reply, "timeline": evidence}

    @bp.get("/api/planner/calendar.ics")
    def export():
        return Response(calendar(current()), mimetype="text/calendar",
                        headers={"Content-Disposition": 'attachment; filename="workouts.ics"'})

    @bp.post("/api/planner")
    def post():
        request.max_content_length = 32_768
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return {"error": "Enter planner details."}, 400

        action = body.get("action")
        if action == "ntfy_test":
            delivery = planner_ntfy.settings(current())
            if not (delivery["available"] and delivery["enabled"]):
                return {"error":"Enable ntfy reminders first."}, 400
            try:
                planner_ntfy.publish(delivery["topic"], "Pebble Health test", "Your workout reminders are connected.")
            except (OSError, ValueError):
                return {"error":"ntfy rejected the test notification. Check the topic and publisher access."}, 502
            return {"ok": True}
        if action == "test_model":
            if not trainer_ready():
                return {"error": "Trainer is unavailable."}, 503
            try:
                settings = planner_context.model_settings(body)
            except ValueError as error:
                return {"error": str(error)}, 400
            fixture = {"timezone":"UTC", "workouts":[], "messages":[], "options":[],
                       "priorities":"", "activities":"", "goals":"", "availability":"",
                       "model_settings":dict(settings, web_search=False)}
            try:
                trainer(fixture, "Reply with one short sentence confirming the connection. Use an empty options array.", None, synthetic=True)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                return {"error":"The router did not return a valid Trainer response."}, 502
            return {"ok":True}
        if action == "chat":
            if not trainer_ready():
                return {"error": "Trainer is unavailable. You can still edit your calendar."}, 503
            state = current()
            if body.get("revision") != state["revision"]:
                return {"error": "The planner changed. Refresh and try again."}, 409
            try:
                message = text(body.get("message"), 3000, True)
                context_id = body.get("workout_id")
                context = next((item for item in state["workouts"] if item["id"] == context_id), None)
                reschedule = body.get("reschedule") is True
                if reschedule and context is None:
                    raise ValueError("Select a workout to reschedule.")
            except ValueError as error:
                return {"error": str(error)}, 400
            try:
                with closing(fitness.connect()) as db, db:
                    planner_context.archive(db, state["messages"])
                    state["_recall"] = planner_context.recall(db, message)
                reply, options, notes = trainer(state, message, context, reschedule)
                explicit = re.match(r"^remember(?: that)?\s*[:,-]?\s+(.+)$", message, re.I | re.S)
                if explicit and len(explicit.group(1)) <= 400:
                    notes.insert(0, explicit.group(1))
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                return {"error": "Trainer could not return a valid reply. Try again."}, 502

        def change(state):
            if action == "setup":
                fields = ("priorities", "activities", "goals", "availability")
                state.update({key: text(body.get(key, ""), 1500) for key in fields})
                timezone = text(body.get("timezone"), 100, True)
                zone = ZoneInfo(timezone)
                for item in state["workouts"]:
                    session(item, zone, item["id"])
                state.update(timezone=timezone, morning=clock(body["morning"]) if body.get("morning") else "",
                             follow_up=body.get("follow_up") is True)
            elif action == "ntfy_settings":
                state["ntfy"] = planner_ntfy.configure(body, state.get("ntfy", {}))
            elif action == "model_settings":
                state["model_settings"] = planner_context.model_settings(body)
            elif action == "forget_note":
                note = body.get("note")
                state["notes"] = [value for value in state.get("notes", []) if value != note]
            elif action in ("save", "delete"):
                ident = body.get("id")
                workouts = state["workouts"]
                if (ident or action == "delete") and not any(item["id"] == ident for item in workouts):
                    raise ValueError("Workout no longer exists.")
                state["workouts"] = [item for item in workouts if item["id"] != ident]
                if action == "save":
                    state["workouts"].append(session(body, ZoneInfo(state["timezone"]), ident))
            elif action == "status":
                item = next((row for row in state["workouts"] if row["id"] == body.get("id")), None)
                if item is None or body.get("status") not in ("planned", "done", "skipped", "rescheduled"):
                    raise ValueError("Choose a workout and completion status.")
                item["status"] = body["status"]
            elif action == "chat":
                at = datetime.now(UTC).isoformat()
                pair = [{"role": "user", "text": message, "at":at},
                        {"role": "trainer", "text": reply, "at":at}]
                state["messages"] = (state["messages"] + pair)[-40:]
                state["notes"] = list(dict.fromkeys(state.get("notes", []) + notes))[-100:]
                state["options"] = options
                return
            elif action == "accept":
                option = next((o for o in state["options"] if o["id"] == body.get("id")), None)
                if option is None:
                    raise ValueError("That option has expired. Ask Trainer for a current proposal.")
                zone = ZoneInfo(state["timezone"])
                today = datetime.now(zone).date().isoformat()
                retained = []
                for item in state["workouts"]:
                    if item["id"] not in option["remove_ids"]:
                        retained.append(item)
                    elif item["start"][:10] < today:
                        prior = item.get("status", "planned")
                        if prior == "planned":
                            item["status"] = "rescheduled" if option.get("reschedule") else "skipped"
                        retained.append(item)
                state["workouts"] = retained + option["workouts"]
            else:
                raise ValueError("Unknown calendar action.")
            state["options"] = []

        try:
            update(body, change)
        except Conflict as error:
            return {"error": str(error)}, 409
        except (ValueError, TypeError, ZoneInfoNotFoundError) as error:
            return {"error": str(error)}, 400
        return get()

    return bp
