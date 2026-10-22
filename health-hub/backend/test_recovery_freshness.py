"""A historical training baseline is not today's recovery input."""
from datetime import date, timedelta
import pytest
import recovery

TODAY = date(2026, 10, 22)


def series(end):
    return [{'date': (end - timedelta(days=41-i)).isoformat(), 'complete': True,
             'acute': 20.0, 'chronic': 30.0} for i in range(42)]


def test_yesterday_is_ready_even_with_open_today_and_unsorted_history():
    rows = series(TODAY-timedelta(days=1))
    state = recovery.training_state(list(reversed(rows)) + [{'date': str(TODAY), 'complete': False}], today=TODAY)
    assert state['status'] == 'ready'
    assert state['age_days'] == 1
    assert state['consecutive_days'] == 42


def test_old_streak_is_stale_and_unknown_gap_does_not_extend_it():
    rows = series(TODAY-timedelta(days=3))
    state = recovery.training_state(rows, today=TODAY)
    assert state['status'] == 'stale'
    assert state['consecutive_days'] == 42
    rows += [{'date': str(TODAY-timedelta(days=1)), 'complete': True, 'acute': 20, 'chronic': 30}]
    assert recovery.training_state(rows, today=TODAY)['consecutive_days'] == 1
    assert recovery.training_state(series(TODAY+timedelta(days=42)), today=TODAY) is None


@pytest.mark.parametrize('day', [str(TODAY-timedelta(days=2)), str(TODAY+timedelta(days=1)), None])
def test_readiness_independently_rejects_old_future_or_undated_ready_load(day):
    load={'status':'ready','acute':20,'chronic':30,'consecutive_days':42,'date':day}
    result=recovery.readiness([], {'score':75,'sleep_s':8*3600}, load, TODAY)
    assert 'training_load' not in result['components']
    assert result['score'] is None
    assert any('stale or undated' in reason for reason in result['missing'])


def test_fresh_load_can_contribute_and_build_passes_its_reference_day():
    load=recovery.training_state(series(TODAY-timedelta(days=1)), today=TODAY)
    result=recovery.readiness([], {'score':75,'sleep_s':8*3600}, load, TODAY)
    assert 'training_load' in result['components']
    assert result['status'] == 'experimental'
    # Historical rebuild must not accidentally use the machine's current date.
    from datetime import datetime
    now=datetime(2026,10,22,12,tzinfo=recovery.TZ).timestamp()
    built=recovery.build([], [], {}, series(TODAY-timedelta(days=1)), now)
    assert 'training_load' in built['readiness']['components']
