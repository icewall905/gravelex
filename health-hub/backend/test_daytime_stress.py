from datetime import datetime, timezone
import daytime_stress

NOW = int(datetime(2026, 10, 26, 12, tzinfo=timezone.utc).timestamp())


def minutes(days=4):
    return [dict(ts=NOW-d*86400-i*60, hr=60 if d else 80, steps=0, active=0)
            for d in range(days) for i in range(60)]


def build(rows, sleeps=(), workouts=(), now=NOW):
    return daytime_stress.build(rows, sleeps, workouts, now, timezone.utc)


def test_baseline_prior_days_and_elevated_pulse():
    result = build(minutes())
    assert result['score'] == 75
    assert result['daily'][-1]['baseline_days'] == 3
    assert build(minutes(3))['score'] is None


def test_motion_unknown_and_future_do_not_score():
    for field, value in [('steps', None), ('active', None), ('steps', 1), ('active', 1), ('hr', 0)]:
        rows = minutes()
        for row in rows:
            if row['ts'] >= NOW-3600:
                row[field] = value
        assert build(rows)['score'] is None
    assert build(minutes(), now=NOW-4*86400)['points'] == []


def test_sleep_workout_and_recovery_excluded():
    session = {'start': NOW-3600, 'seconds': 3601}
    assert build(minutes(), sleeps=[session])['score'] is None
    assert build(minutes(), workouts=[session])['score'] is None
    assert build(minutes(), workouts=[{'start': NOW-3600, 'seconds':3000}])['score'] is None


def test_stale_and_gaps():
    assert build(minutes(), now=NOW+3601)['score'] is None
    rows = minutes()
    rows = [r for r in rows if not (NOW-600 < r['ts'] <= NOW)]
    result = build(rows)
    assert all(p['observed_at'] <= NOW-600 for p in result['points'])
