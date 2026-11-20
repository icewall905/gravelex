from datetime import datetime, timezone

import briefing
import fitness
import recovery


def test_sleep_intervals_merge_and_gaps_are_not_inferred_from_daily_totals():
    start = datetime(2026, 10, 21, 23, tzinfo=timezone.utc).timestamp()
    nights = recovery.nightly_sleep([
        {'start': start, 'seconds': 7200, 'kind': 'sleep'},
        {'start': start + 3600, 'seconds': 3600, 'kind': 'sleep'},
        {'start': start + 7800, 'seconds': 14400, 'kind': 'sleep'},
        {'start': start + 600, 'seconds': 1200, 'kind': 'restful_sleep'},
    ], {})
    assert nights[0]['recorded_gaps'] == [(start + 7200, start + 7800)]
    assert len(nights[0]['sleep_intervals']) == 2
    assert nights[0]['sleep_s'] == 21600
    daily = recovery.nightly_sleep([], {'2026-10-22': (25000, 10000)})[0]
    assert 'recorded_gaps' not in daily
    assert daily['onset'] is None


def test_analysis_has_dated_workouts_and_sleep_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(fitness, 'DB_PATH', str(tmp_path / 'sleep.sqlite3'))
    summary = fitness.summary(7)
    now = int(datetime(2026, 10, 22, 12, tzinfo=timezone.utc).timestamp())
    onset = now - 13*3600
    summary['now'] = now
    summary['recovery']['sleep_nights'] = [
        {'night': '2026-10-22', 'source': 'sessions', 'sleep_s': 21600,
         'restful_s': 10000, 'onset': onset, 'wake': onset + 22200,
         'sleep_intervals': [(onset, onset+7200), (onset+7800, onset+22200)],
         'restful_intervals': [], 'recorded_gaps': [(onset+7200, onset+7800)]},
        {'night': '2026-10-23', 'sleep_s': 99999, 'restful_s': 0}]
    summary['workouts'] = [
        {'start': onset-7200, 'seconds': 3600, 'kind': 'run', 'rpe': 7, 'load': 50},
        {'start': now-3600, 'seconds': 600, 'kind': 'walk'},
        {'start': onset-7200, 'seconds': 3600, 'excluded': True},
        {'start': now+3600, 'seconds': 600}]
    result = briefing.facts(summary, timezone.utc)['sleep']
    assert result['nights_recorded_last_7'] == 1
    assert result['last_night_detail']['gap_duration'] == '0h 10m'
    assert result['last_night_detail']['gap_count'] == 1
    assert result['last_night_detail']['recorded_gaps'][0]['start'].endswith('+00:00')
    assert len(result['recent_workouts']) == 2
    assert result['recent_workouts'][0]['hours_before_last_sleep'] == 1
    assert result['recent_workouts'][0]['rpe'] == 7
    assert result['recent_workouts'][1]['before_last_sleep'] is False
    assert result['recent_workouts'][1]['hours_before_last_sleep'] is None
