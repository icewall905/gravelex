"""Direct history uploads must not replace the watch's current snapshot."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'bridge'))
import fitness


def test_history_does_not_replace_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(fitness, 'DB_PATH', str(tmp_path / 'fitness.sqlite3'))
    now = int(time.time())
    fitness.ingest({'ts': now-60, 'source': 'watch', 'status': {'steps': 1234, 'heart_rate_bpm': 64}})
    fitness.ingest({'ts': now, 'source': 'gravelex', 'records': [
        {'ts': now-30, 'steps': 12, 'hr': 71, 'active': 0}],
        'sessions': [{'id': 'sample', 'start': now-600, 'seconds': 120, 'type': 'walk'}]})
    result = fitness.summary(7)
    assert result['latest']['status']['steps'] == 1234
    with fitness.connect() as db:
        assert db.execute('SELECT hr FROM minutes WHERE ts=?', (now-30,)).fetchone()[0] == 71
        assert db.execute('SELECT COUNT(*) FROM workouts').fetchone()[0] == 1


def test_history_hr_never_overwrites_newer_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(fitness, 'DB_PATH', str(tmp_path / 'fitness.sqlite3'))
    now = int(time.time())
    fitness.ingest({'ts': now-60, 'source': 'watch', 'status': {'heart_rate_bpm': 64}})
    fitness.ingest({'ts': now, 'source': 'gravelex', 'records': [
        {'ts': now-120, 'steps': 12, 'hr': 71, 'active': 0}]})
    with fitness.connect() as db:
        assert fitness.ha_history_status(db, now) == {}
    fitness.ingest({'ts': now, 'source': 'gravelex', 'records': [
        {'ts': now-30, 'steps': 12, 'hr': 72, 'active': 0}]})
    with fitness.connect() as db:
        status = fitness.ha_history_status(db, now)
        assert status['heart_rate_bpm'] == 72
        assert status['heart_rate_ts'] == now-30
        assert 'steps' not in status
