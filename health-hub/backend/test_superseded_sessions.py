import training

DAY = "2026-11-25"
START = 1795593600  # 2026-11-25 06:00 Europe/Copenhagen-ish; only overlap matters


def _analyze(workouts):
    return training.analyze(workouts, [], [__import__("datetime").date.fromisoformat(DAY)],
                            None, "rpe", {})


def test_watch_walk_overlapping_phone_walk_drops_out_and_phone_counts():
    phone = {"id": "phone:a", "start": START, "seconds": 1800, "kind": "walk", "rpe": 3}
    watch = {"id": "pebble:%d:walk" % (START + 120), "start": START + 120, "seconds": 1500, "kind": "walk"}
    out = {w["id"]: w for w in _analyze([phone, watch])["workouts"]}
    assert out[watch["id"]]["superseded_by"] == "phone:a"
    assert out[watch["id"]]["ignored"] and out[watch["id"]]["excluded"]
    assert not out["phone:a"]["excluded"] and not out["phone:a"]["overlap"]
    assert out["phone:a"]["load"] == 90.0


def test_two_watch_sessions_overlapping_stay_ambiguous():
    a = {"id": "pebble:1:walk", "start": START, "seconds": 600, "kind": "walk"}
    b = {"id": "pebble:2:run", "start": START + 300, "seconds": 600, "kind": "run"}
    out = _analyze([a, b])["workouts"]
    assert all(w["overlap"] and w["excluded"] and "superseded_by" not in w for w in out)


def test_removed_phone_recording_does_not_hide_watch_session():
    phone = {"id": "phone:a", "start": START, "seconds": 1800, "kind": "walk", "ignored": True}
    watch = {"id": "pebble:9:walk", "start": START, "seconds": 1800, "kind": "walk"}
    assert training.superseded([phone, watch]) == {}


def test_watch_session_gets_distance_from_minutes():
    watch = {"id": "pebble:1:walk", "start": START, "seconds": 180, "kind": "walk"}
    minutes = [{"ts": START + i * 60, "hr": 100, "payload": '{"distance_m": 80.5}'} for i in range(4)]
    out = training.analyze([watch], minutes, [__import__("datetime").date.fromisoformat(DAY)], None, "rpe", {})
    assert out["workouts"][0]["distance_m"] == 241.5
