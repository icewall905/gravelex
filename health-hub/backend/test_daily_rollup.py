"""Daily rollups, nap separation and night assignment."""
import json
import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import daily
import fitness
import recovery

CPH = ZoneInfo("Europe/Copenhagen")


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE minutes(ts INTEGER PRIMARY KEY, hr INTEGER, steps INTEGER, active INTEGER, payload TEXT)")
    conn.execute("CREATE TABLE sleep_sessions(id TEXT PRIMARY KEY, start INTEGER, seconds INTEGER, kind TEXT)")
    yield conn
    conn.close()


def at(day, hour, minute=0):
    return int(datetime(day.year, day.month, day.day, hour, minute, tzinfo=CPH).timestamp())


def add(db, ts, hr=None, steps=0, active=0, **payload):
    db.execute("INSERT INTO minutes VALUES(?,?,?,?,?)", (ts, hr, steps, active, json.dumps(payload)))


def test_rollup_counts_local_days_and_keeps_missing_days_unknown(db):
    d = date(2026, 11, 3)
    add(db, at(d, 0, 30), hr=50, steps=0)
    add(db, at(d, 23, 59), hr=90, steps=100, active=1, active_kcal=2.5, distance_m=70)
    add(db, at(date(2026, 11, 4), 0, 0), hr=200, steps=7)
    rows = daily.rollup(db, date(2026, 11, 2), date(2026, 11, 4), CPH, at(date(2026, 11, 5), 0))
    assert [r["date"] for r in rows] == ["2026-11-02", "2026-11-03", "2026-11-04"]
    assert rows[0]["steps"] is None and rows[0]["minutes"] == 0
    assert (rows[1]["steps"], rows[1]["active_minutes"], rows[1]["hr_minutes"]) == (100, 1, 2)
    assert (rows[1]["hr_min"], rows[1]["hr_max"], rows[1]["hr_avg"]) == (50, 90, 70.0)
    assert rows[1]["active_kcal"] == 2.5 and rows[1]["distance_m"] == 70
    assert rows[2]["steps"] == 7


def test_rollup_handles_dst_day_and_resting_hr(db):
    d = date(2026, 10, 25)  # 25-hour day in Copenhagen
    for i in range(30):
        add(db, at(d, 1) + i * 60, hr=48 + i % 5)
    add(db, at(d, 23, 30), steps=5)
    rows = daily.rollup(db, d, d, CPH, at(date(2026, 10, 26), 12))
    assert rows[0]["minutes"] == 31 and rows[0]["steps"] == 5
    assert rows[0]["resting_hr"] == 48


def test_future_minutes_are_excluded(db):
    d = date(2026, 11, 3)
    add(db, at(d, 12), steps=10)
    add(db, at(d, 20), steps=99)
    rows = daily.rollup(db, d, d, CPH, at(d, 13))
    assert rows[0]["steps"] == 10


def test_intraday_buckets_and_sleep(db):
    d = date(2026, 11, 3)
    add(db, at(d, 8, 1), hr=70, steps=10)
    add(db, at(d, 8, 14), hr=0 or None, steps=5)
    add(db, at(d, 8, 16), steps=3)
    db.execute("INSERT INTO sleep_sessions VALUES('a',?,?,'sleep')", (at(d, 0, 30), 6 * 3600))
    out = daily.intraday(db, d, CPH, at(d, 23))
    assert [b["steps"] for b in out["steps_15min"]] == [15, 3]
    assert out["points"][0]["hr"] == 70 and len(out["sleep"]) == 1


def test_ingest_separates_naps(tmp_path, monkeypatch):
    now = 1795000000
    monkeypatch.setattr(fitness, "DB_PATH", str(tmp_path / "h.sqlite3"))
    monkeypatch.setattr(fitness.time, "time", lambda: now)
    fitness.ingest({"source": "gravelex", "ts": now, "records": [], "sessions": [
        {"start": now - 7200, "seconds": 3600, "type": "sleep", "raw_overlay_type": 3},
        {"start": now - 7000, "seconds": 600, "type": "restful_sleep", "raw_overlay_type": 4},
        {"start": now - 40000, "seconds": 20000, "type": "sleep", "raw_overlay_type": 1}]})
    with fitness.connect() as db:
        kinds = sorted(r[0] for r in db.execute("SELECT kind FROM sleep_sessions"))
    assert kinds == ["nap", "restful_nap", "sleep"]


def test_reclassify_existing_naps(tmp_path, monkeypatch):
    now = 1795000000
    monkeypatch.setattr(fitness, "DB_PATH", str(tmp_path / "h.sqlite3"))
    monkeypatch.setattr(fitness.time, "time", lambda: now)
    with fitness.connect() as db:
        db.execute("INSERT INTO sleep_sessions VALUES(?,?,?,?)", (f"pebble:{now-7200}:sleep", now - 7200, 3600, "sleep"))
        db.execute("INSERT INTO reports VALUES(?,?,?,?)", (now, "gravelex", now, json.dumps(
            {"sessions": [{"start": now - 7200, "seconds": 3600, "type": "sleep", "raw_overlay_type": 3}]})))
        assert fitness.reclassify_naps(db) == 1
        assert fitness.reclassify_naps(db) == 0
        assert db.execute("SELECT id,kind FROM sleep_sessions").fetchall()[0]["kind"] == "nap"


def test_naps_do_not_join_nights_and_evening_start_uses_midpoint(monkeypatch):
    monkeypatch.setattr(recovery, "TZ", CPH)
    d = date(2026, 11, 19)
    sessions = [
        {"start": at(d, 10, 18), "seconds": 3900, "kind": "nap"},
        {"start": at(date(2026, 11, 18), 17, 59), "seconds": 5100, "kind": "sleep"},
        {"start": at(date(2026, 11, 18), 23, 0), "seconds": 6 * 3600, "kind": "sleep"},
    ]
    nights = recovery.nightly_sleep(sessions, {})
    assert [n["night"] for n in nights] == ["2026-11-19"]
    assert nights[0]["sleep_s"] == 5100 + 6 * 3600
