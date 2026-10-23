from datetime import date, timedelta
import pytest
import training
import training_ledger as ledger

TODAY = date(2026, 10, 22)
YESTERDAY = TODAY - timedelta(days=1)


def analyzed(confirmations, workouts=None):
    days = [TODAY - timedelta(days=n) for n in range(43)]
    return training.analyze(workouts or [], [], days, 190, load_method='rpe', confirmations=confirmations)


def session(day=YESTERDAY, **values):
    result = {'start': day.isoformat() + 'T12:00:00', 'seconds': 600, 'rpe': 4}
    result.update(values)
    return result


def test_open_today_does_not_reset_finished_baseline():
    confirmations = {(TODAY - timedelta(days=n)).isoformat(): 'rest' for n in range(1, 43)}
    result = analyzed(confirmations)
    assert result['latest']['baseline_days'] == 0
    out = ledger.build(result, confirmations, [], TODAY)
    assert out['confirmed_consecutive_days'] == 42
    assert out['status'] == 'ready'
    assert out['today']['status'] == 'open'
    assert out['blockers'] == []


def test_gap_names_exact_day_and_coverage_does_not_infer_rest():
    confirmations = {(TODAY - timedelta(days=n)).isoformat(): 'rest' for n in range(1, 43)}
    gap = (TODAY - timedelta(days=4)).isoformat()
    del confirmations[gap]
    out = ledger.build(analyzed(confirmations), confirmations,
                       [{'date': gap, 'hr_minutes': 1440, 'hr_coverage_pct': 100}], TODAY)
    assert out['confirmed_consecutive_days'] == 3
    assert out['missing_days'] == [gap]
    assert out['confirmed_days'] == 41
    assert out['blockers'][0]['date'] == gap


def test_partial_preserves_recorded_method_load():
    workouts = [session()]
    result = analyzed({}, workouts)
    out = ledger.build(result, {}, [], TODAY)
    row = out['days'][-1]
    assert row['status'] == 'partial'
    assert row['confirmed_load'] is None
    assert row['recorded_rpe_load'] == 40
    assert row['recorded_hr_load'] is None


def test_batch_complete_rest_clear_and_ignored_sessions():
    workouts = analyzed({}, [session()])['workouts']
    key = YESTERDAY.isoformat()
    assert ledger.validate_batch([{'date': key, 'status': 'complete'}], workouts, TODAY)[0]['status'] == 'complete'
    assert ledger.validate_batch([{'date': key, 'status': 'unknown'}], workouts, TODAY)[0]['status'] == 'unknown'
    with pytest.raises(ValueError, match='prevent a rest'):
        ledger.validate_batch([{'date': key, 'status': 'rest'}], workouts, TODAY)
    ignored = analyzed({}, [session(ignored=True)])['workouts']
    assert ledger.validate_batch([{'date': key, 'status': 'rest'}], ignored, TODAY)


@pytest.mark.parametrize('delta', [0, 1])
def test_no_open_or_future_days(delta):
    with pytest.raises(ValueError, match='finished'):
        ledger.validate_batch([{'date': (TODAY + timedelta(days=delta)).isoformat(), 'status': 'rest'}], [], TODAY)


def test_duplicates_and_bound():
    item = {'date': YESTERDAY.isoformat(), 'status': 'rest'}
    with pytest.raises(ValueError, match='unique'):
        ledger.validate_batch([item, item], [], TODAY)
    for items in ([], [item] * 43):
        with pytest.raises(ValueError, match='1 to 42'):
            ledger.validate_batch(items, [], TODAY)


@pytest.mark.parametrize('workouts', [[session(rpe=None)], [session(), session()]])
def test_unscoreable_or_overlapping_sessions_cannot_be_confirmed(workouts):
    result = analyzed({}, workouts)
    with pytest.raises(ValueError, match='valid selected-method load'):
        ledger.validate_batch([{'date': YESTERDAY.isoformat(), 'status': 'complete'}], result['workouts'], TODAY)


def test_invalid_complete_confirmation_is_partial():
    confirmations = {YESTERDAY.isoformat(): 'complete'}
    out = ledger.build(analyzed(confirmations, [session(rpe=None)]), confirmations, [], TODAY)
    assert out['days'][-1]['status'] == 'partial'
    assert YESTERDAY.isoformat() in out['partial_days']
    assert out['days'][-1]['blockers']
