import sqlite3
from datetime import UTC, datetime

import planner_ntfy


def test_due_reminders_are_sent_once_and_exclude_skipped(monkeypatch):
    monkeypatch.setenv("PH_NTFY_URL", "https://notify.example.invalid")
    sent = []
    monkeypatch.setattr(planner_ntfy, "publish", lambda *args: sent.append(args))
    state = {
        "timezone": "Europe/Copenhagen", "morning": "08:00", "follow_up": True,
        "ntfy": {"enabled": True, "topic": "private-test-topic"},
        "workouts": [
            {"id": "planned", "start": "2026-11-21T09:00", "minutes": 45, "status": "planned"},
            {"id": "skipped", "start": "2026-11-21T09:00", "minutes": 45, "status": "skipped"},
        ],
    }
    db = sqlite3.connect(":memory:")
    planner_ntfy.deliver(db, state, datetime(2026, 11, 21, 7, 5, tzinfo=UTC))
    planner_ntfy.deliver(db, state, datetime(2026, 11, 21, 7, 6, tzinfo=UTC))
    assert [(record[1], record[3]) for record in sent] == [("You have a workout today", "planned")]
    planner_ntfy.deliver(db, state, datetime(2026, 11, 21, 9, 46, tzinfo=UTC))
    assert [(record[1], record[3]) for record in sent] == [
        ("You have a workout today", "planned"), ("How did training go?", "planned"),
    ]


def test_failed_publish_is_retried_after_lease(monkeypatch):
    monkeypatch.setenv("PH_NTFY_URL", "https://notify.example.invalid")
    failures = []
    def publish(*args):
        failures.append(args)
        if len(failures) == 1:
            raise OSError("synthetic outage")
    monkeypatch.setattr(planner_ntfy, "publish", publish)
    state = {
        "timezone":"UTC", "morning":"08:00", "follow_up":False,
        "ntfy":{"enabled":True,"topic":"private-test-topic"},
        "workouts":[{"id":"planned", "start":"2026-11-21T09:00", "minutes":30}],
    }
    db = sqlite3.connect(":memory:")
    for minute in (0, 1, 2, 3):
        planner_ntfy.deliver(db, state, datetime(2026, 11, 21, 8, minute, tzinfo=UTC))
    assert len(failures) == 2
    assert db.execute("SELECT sent FROM planner_ntfy_deliveries").fetchone()[0] == 1
