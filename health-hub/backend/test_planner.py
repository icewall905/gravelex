from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import fitness
import planner
from test_dashboard_auth import client, login


def test_manual_calendar_conflicts_and_history(client):
    assert client.get("/api/planner").status_code == 401
    assert client.get("/planner.html?android=1").location == "/login?planner=1&android=1"
    assert login(client).status_code == 200
    assert client.get("/planner.html").status_code == 200
    headers = {"X-PH-Request": "1"}

    def post(**body):
        return client.post("/api/planner", json=body, headers=headers)

    setup = post(action="setup", revision=0, timezone="Europe/Copenhagen", morning="08:00", follow_up=True)
    assert setup.status_code == 200
    workout = dict(title="Running, easy", start="2026-11-07T10:00", minutes=45, details="Warm up\nRun")
    assert post(action="save", revision=0, **workout).status_code == 409
    saved = post(action="save", revision=1, **workout).json
    item = saved["workouts"][0]
    assert item["status"] == "planned"
    assert item["start_ms"] == int(datetime(2026, 11, 7, 9, tzinfo=UTC).timestamp() * 1000)
    done = post(action="status", revision=2, id=item["id"], status="done")
    assert done.json["workouts"][0]["status"] == "done"
    ics = client.get("/api/planner/calendar.ics").get_data(as_text=True)
    assert "DTSTART:20261107T090000Z\r\n" in ics
    assert "SUMMARY:Running\\, easy\r\n" in ics
    assert "DESCRIPTION:Warm up\\nRun\r\n" in ics
    with fitness.connect() as db:
        db.execute("INSERT INTO workouts(id,start,seconds,kind,rpe,source) VALUES(?,?,?,?,?,?)",
                   ("actual", item["start_ms"] // 1000, 2600, "running", 5, "manual"))
    assert client.get("/api/planner/history?month=2026-11").json["workouts"][0]["id"] == "actual"
    assert client.get("/api/planner/history?month=2026-12").json["workouts"] == []
    assert post(action="delete", revision=3, id=item["id"]).json["workouts"] == []


def test_proposals_require_explicit_acceptance(client, monkeypatch):
    monkeypatch.setattr(planner, "trainer_ready", lambda: True)
    assert login(client).status_code == 200
    headers = {"X-PH-Request": "1"}
    captured = []
    saved_start = (datetime.now(UTC).date() + timedelta(days=2)).isoformat() + "T11:00"
    moved_start = (datetime.now(UTC).date() + timedelta(days=3)).isoformat() + "T11:00"

    def trainer(state, message, context, reschedule):
        captured.append(context)
        return "Move your session", [{
            "id": "option", "title": "Saturday", "summary": "",
            "remove_ids": [context["id"]],
            "workouts": [planner.session({"title": "Ride", "start": moved_start, "minutes": 40},
                                         ZoneInfo(state["timezone"]))],
        }], []

    monkeypatch.setattr(planner, "trainer", trainer)
    saved = client.post("/api/planner", headers=headers, json={
        "action":"save", "revision":0, "title":"Ride", "start":saved_start, "minutes":40,
    }).json
    original = saved["workouts"][0]["id"]
    chat = client.post("/api/planner", headers=headers, json={
        "action":"chat", "revision":1, "message":"Move it to Saturday", "workout_id":original,
    }).json
    assert captured[0]["id"] == chat["workouts"][0]["id"] == original
    assert chat["messages"][-1]["text"] == "Move your session"
    accepted = client.post("/api/planner", headers=headers, json={"action":"accept","revision":2,"id":"option"}).json
    assert [item["start"] for item in accepted["workouts"]] == [moved_start]
    assert accepted["options"] == []


def test_reminder_times_and_skipped_status():
    state = {"timezone":"Europe/Copenhagen", "morning":"08:00", "follow_up":True}
    item = planner.session({"title":"Run","start":"2026-11-21T17:00","minutes":45}, ZoneInfo(state["timezone"]))
    state["workouts"] = [item]
    assert [(kind, at.hour, at.minute) for _, kind, at in planner.reminders(state, date(2026, 11, 21))] == [
        ("morning", 7, 0), ("follow-up", 17, 45),
    ]
    item["status"] = "skipped"
    assert list(planner.reminders(state, date(2026, 11, 21))) == []


def test_planner_is_account_scoped(client):
    import accounts

    def create():
        state = planner.update({"revision": 0}, lambda data: data.update(goals="Private goal"))
        assert state["revision"] == 1

    with accounts.as_user({"id": "1" * 32, "legacy": False}):
        create()
    with accounts.as_user({"id": "2" * 32, "legacy": False}):
        with fitness.connect() as db:
            assert planner.read(db)["goals"] == ""
        create()
    with accounts.as_user({"id": "1" * 32, "legacy": False}):
        with fitness.connect() as db:
            assert planner.read(db)["goals"] == "Private goal"


def test_explicit_reschedule_uses_selected_id(client, monkeypatch):
    import json
    today = datetime.now(UTC).date()
    tomorrow = today + timedelta(days=1)
    context = {"id":"origin", "start":str(today)+"T08:00", "minutes":30}
    state = {
        "timezone":"UTC", "priorities":"", "activities":"", "goals":"", "availability":"",
        "workouts":[context], "messages":[], "options":[],
    }
    proposed = {"reply":"Try this new time", "options":[{"title":"New date",
        "remove_ids":["wrong-id"], "workouts":[{
            "title":"Run", "start":str(tomorrow)+"T08:00", "minutes":30,
        }]}, {"title":"Unchanged", "workouts":[{
            "title":"Run", "start":context["start"], "minutes":30,
        }]}]}

    class Opener:
        def open(self, request, timeout):
            import io
            assert json.loads(request.data)["operation"] == "reschedule_selected_workout"
            return io.BytesIO(json.dumps(proposed).encode())

    monkeypatch.setenv("PH_TRAINER_WEBHOOK", "https://trainer.example.invalid")
    monkeypatch.setenv("PH_TRAINER_SECRET", "test-only")
    monkeypatch.setattr(planner, "build_opener", lambda _: Opener())
    monkeypatch.setattr(fitness, "summary", lambda _: {})
    _, options, _ = planner.trainer(state, "Move this run", context, reschedule=True)
    assert len(options) == 1
    assert options[0]["remove_ids"] == ["origin"]
    assert options[0]["reschedule"] is True


def test_trainer_tools_persist_notes_and_history(client, monkeypatch):
    import io
    import json
    import planner_context

    assert login(client).status_code == 200
    headers = {"X-PH-Request": "1"}
    monkeypatch.setenv("PH_TRAINER_WEBHOOK", "https://trainer.example.invalid")
    monkeypatch.setenv("PH_TRAINER_SECRET", "test-only")
    monkeypatch.setenv("PH_TRAINER_SEARCH_URL", "http://search.example.invalid")
    monkeypatch.setattr(fitness, "summary", lambda _: {})
    monkeypatch.setattr(planner_context, "search", lambda query: [
        {"title": "Public reference", "url": "https://example.org/reference", "excerpt": query},
    ])

    class Opener:
        def open(self, request, timeout):
            payload = json.loads(request.data)
            assert payload["model_settings"]["model"] == "fixture-model"
            if payload["web_search_allowed"]:
                result = {"search_query": "public physical activity guidance"}
            else:
                assert payload["web_results"][0]["url"] == "https://example.org/reference"
                result = {"reply": "I will keep that in mind.", "options": [], "memory_notes": ["Owns a bike."]}
            return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setattr(planner, "build_opener", lambda _: Opener())
    settings = client.post("/api/planner", headers=headers, json={
        "action":"model_settings", "revision":0, "base_url":planner_context.defaults()["base_url"],
        "model":"fixture-model", "web_search":True,
    })
    assert settings.status_code == 200
    reply = client.post("/api/planner", headers=headers, json={
        "action":"chat", "revision":1, "message":"Remember that I cycle on Tuesday.",
    })
    assert reply.status_code == 200
    assert reply.json["notes"] == ["I cycle on Tuesday.", "Owns a bike."]
    with fitness.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM planner_conversation").fetchone()[0] == 2
        assert all(row["current"] for row in planner_context.recall(db, "cycling")["last_40_messages"])
    assert client.post("/api/planner", headers=headers, json={
        "action":"forget_note", "revision":2, "note":"Owns a bike.",
    }).json["notes"] == ["I cycle on Tuesday."]


def test_phone_check_in_uses_only_goal_progress_and_does_not_change_state(client, monkeypatch):
    monkeypatch.setattr(planner, "trainer_ready", lambda: True)
    path = "/api/planner/check-in"
    headers = {"X-PH-Request": "1"}
    payload = {"minute": 720, "step_goal": 8000, "weekly_goal": 150,
               "weekly_minutes": 60, "move_behind": True}

    def coach(state, prompt, progress, *, synthetic):
        assert synthetic and not state["model_settings"]["web_search"]
        assert state["workouts"] == state["messages"] == []
        assert progress["weekly_minutes"] == 60
        assert "steps" not in progress and not progress["move_behind"]
        return "An easy walk is a nice way to pick up where you left off.", [], []

    monkeypatch.setattr(planner, "trainer", coach)
    assert client.post(path, json=payload, headers=headers).status_code == 401
    assert login(client).status_code == 200
    assert client.post(path, json=payload).status_code == 403
    before = client.get("/api/planner").json
    assert client.post(path, json={**payload, "step_goal": -1}, headers=headers).status_code == 400
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 200 and "walk" in response.json["message"]
    assert client.get("/api/planner").json == before
