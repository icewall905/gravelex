"""Complementary exports must not erase previously observed minute metrics."""
import json
import time

import pytest
import fitness


@pytest.fixture
def minute_store(tmp_path, monkeypatch):
    monkeypatch.setattr(fitness, 'DB_PATH', str(tmp_path / 'fitness.sqlite3'))
    return int(time.time()) - 120


def upload(rows):
    fitness.ingest({'records': rows})


def stored(ts):
    with fitness.connect() as db:
        row = dict(db.execute('SELECT * FROM minutes WHERE ts=?', (ts,)).fetchone())
    payload = json.loads(row.pop('payload'))
    for key in ('ts', 'hr', 'steps', 'active'):
        assert payload[key] == row[key]
    return row, payload


@pytest.mark.parametrize('reverse', [False, True])
def test_complementary_uploads_in_both_orders(minute_store, reverse):
    ts = minute_store
    rows = [{'ts': ts, 'hr': 72, 'quality': 5},
            {'ts': ts, 'steps': 42, 'active': 1, 'device': 'watch'}]
    for row in rows[::-1] if reverse else rows:
        upload([row])
    row, payload = stored(ts)
    assert row == {'ts': ts, 'hr': 72, 'steps': 42, 'active': 1}
    assert payload['quality'] == 5
    assert payload['device'] == 'watch'


def test_sparse_null_replays_zero_corrections_and_duplicate_idempotency(minute_store):
    ts = minute_store
    upload([{'ts': ts, 'hr': 75, 'steps': 20, 'active': 1, 'quality': 4}])
    upload([{'ts': ts, 'hr': None, 'steps': None, 'active': None}])
    assert stored(ts)[0] == {'ts': ts, 'hr': 75, 'steps': 20, 'active': 1}
    correction = {'ts': ts, 'hr': 65, 'steps': 0, 'active': 0}
    upload([correction])
    expected = stored(ts)
    upload([correction])
    assert stored(ts) == expected
    assert expected[0] == {'ts': ts, 'hr': 65, 'steps': 0, 'active': 0}
    assert expected[1]['quality'] == 4
    with fitness.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM minutes').fetchone()[0] == 1


def test_new_sparse_row_keeps_unknown_metrics(minute_store):
    upload([{'ts': minute_store, 'extra': 'retained'}])
    assert stored(minute_store)[0] == {'ts': minute_store, 'hr': None, 'steps': None, 'active': None}


@pytest.mark.parametrize('invalid', [None, [], 12, {'hr': True}, {'hr': False},
    {'hr': 301}, {'hr': '70'}, {'hr': float('nan')}, {'hr': 65.5},
    {'steps': -1}, {'steps': True}, {'steps': 10001}, {'steps': 0.5},
    {'active': 2}, {'active': False}, {'active': 0.5}])
def test_invalid_batch_rolls_back_all_changes(minute_store, invalid):
    ts = minute_store
    upload([{'ts': ts, 'hr': 70, 'steps': 12}])
    before = stored(ts)
    bad = dict(invalid, ts=ts+60) if isinstance(invalid, dict) else invalid
    with pytest.raises(ValueError):
        fitness.ingest({'ts': ts, 'source': 'invalid-batch',
                        'records': [{'ts': ts, 'hr': 90}, bad]})
    assert stored(ts) == before
    with fitness.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM minutes').fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM reports WHERE source='invalid-batch'").fetchone()[0] == 0


def test_legacy_zero_hr_sentinel_in_mixed_batch(minute_store):
    ts = minute_store
    upload([{'ts': ts, 'hr': 0, 'steps': 0, 'active': 0},
            {'ts': ts + 60, 'hr': 71, 'steps': 3, 'active': 1}])
    assert stored(ts)[0] == {'ts': ts, 'hr': None, 'steps': 0, 'active': 0}
    assert stored(ts + 60)[0]['hr'] == 71
    upload([{'ts': ts + 60, 'hr': 0.0}])
    assert stored(ts + 60)[0]['hr'] == 71
