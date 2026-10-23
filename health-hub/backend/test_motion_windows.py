import json
import time

import pytest

import fitness
import motion_quality


def windows(short=False, bad_peak=False):
    rows = []
    for i in range(36):
        samples = 0 if short and i == 7 else (501 if i == 0 else 500)
        transitions = 0 if samples == 0 else 500
        total = 0 if samples == 0 else (10000 if bad_peak and i == 7 else transitions)
        rows.append({'start_ms': i * 5000, 'samples': samples, 'transitions': transitions,
                     'total_delta': total, 'max_delta': total if bad_peak and i == 7 else 1})
    return {'version': 1, 'window_ms': 5000, 'clock': 'callback_receipt', 'windows': rows}


def payload(**extra):
    out = {'motion_samples': 18001, 'motion_total': 18000,
           'motion_source': 'raw_accelerometer', 'firmware': 'fw',
           'collector_version': 153, 'offsets_ms': [i * 1000 for i in range(181)]}
    out.update(extra)
    return out


def policy(**extra):
    out = {'id': 'synthetic-test-only', 'evidence': 'unit-test-only',
           'source': 'raw_accelerometer', 'firmware': 'fw', 'collector_version': 153,
           'sample_hz': 100, 'max_mean_delta': 2, 'min_coverage': .9,
           'motion_window_version': 1, 'window_ms': 5000,
           'max_window_mean_delta': 2, 'max_transition_delta': 2,
           'min_window_coverage': .9}
    out.update(extra)
    return out


def test_valid_contract_normalizes_and_reconciles():
    result = motion_quality.validate_windows(windows(), 18000, 18001)
    assert len(result['windows']) == 36
    assert result['windows'][0]['start_ms'] == 0


@pytest.mark.parametrize('change', [
    lambda x: x.update(version=True),
    lambda x: x.update(window_ms=True),
    lambda x: x['windows'].pop(),
    lambda x: x['windows'][1].update(start_ms=5001),
    lambda x: x['windows'][2].update(samples=True),
    lambda x: x['windows'][3].update(max_delta=0, total_delta=1),
])
def test_contract_rejects_bad_shape_or_bool(change):
    data = windows()
    change(data)
    with pytest.raises(ValueError):
        motion_quality.validate_windows(data, 18000, 18001)


def test_short_burst_diluted_global_mean_is_rejected_by_window_policy(monkeypatch):
    burst = windows(bad_peak=True)
    data = payload(motion_total=sum(w['total_delta'] for w in burst['windows']), motion_windows=burst)
    monkeypatch.setenv('HRV_MOTION_POLICIES', json.dumps([policy()]))
    result = motion_quality.assess(data)
    assert result['status'] == 'excessive'
    assert result['max_window_mean'] > result['normalized_mean']


def test_per_window_gap_is_rejected(monkeypatch):
    data = windows()
    data['windows'][12]['samples'] = 100
    data['windows'][12]['transitions'] = 100
    data['windows'][12]['total_delta'] = 100
    # Keep global reconciliation exact by taking the same count from another bucket.
    data['windows'][13]['samples'] = 900
    data['windows'][13]['transitions'] = 900
    data['windows'][13]['total_delta'] = 900
    monkeypatch.setenv('HRV_MOTION_POLICIES', json.dumps([policy()]))
    result = motion_quality.assess(payload(motion_windows=data))
    assert result['status'] == 'coverage_inconsistent'


def test_watch153_missing_windows_and_legacy_policy_fail_closed(monkeypatch):
    monkeypatch.setenv('HRV_MOTION_POLICIES', json.dumps([policy(motion_window_version=None)]))
    result = motion_quality.assess(payload())
    assert result['status'] == 'missing_windows'
    result = motion_quality.assess(payload(motion_windows=windows()))
    assert result['status'] == 'invalid_policy'


def test_valid_synthetic_window_policy_passes(monkeypatch):
    monkeypatch.setenv('HRV_MOTION_POLICIES', json.dumps([policy()]))
    result = motion_quality.assess(payload(motion_windows=windows()))
    assert result['eligible'] is True
    assert result['max_delta'] == 1


def test_legacy_152_without_windows_unchanged(monkeypatch):
    monkeypatch.setenv('HRV_MOTION_POLICIES', json.dumps([policy(collector_version=152,
                                                                  sample_hz=25,
                                                                  motion_window_version=None,
                                                                  window_ms=None,
                                                                  max_window_mean_delta=None,
                                                                  max_transition_delta=None,
                                                                  min_window_coverage=None)]))
    result = motion_quality.assess(payload(collector_version=152, motion_samples=4501,
                                            motion_total=4500, offsets_ms=[i * 1000 for i in range(181)],
                                            sample_hz=25))
    assert result['eligible'] is True


def test_hrv_ingest_roundtrip_and_corrupt_rejection(monkeypatch, tmp_path):
    db_path = tmp_path / 'fitness.sqlite3'
    monkeypatch.setattr(fitness, 'DB_PATH', str(db_path))
    now = int(time.time())
    data = {'ts': now, 'ppi': [900, 901], 'offsets_ms': [0, 1000],
            'motion_samples': 18001, 'motion_total': 18000,
            'motion_windows': windows(), 'collector_version': 153,
            'motion_source': 'raw_accelerometer'}
    result = fitness.hrv_ingest(data)
    assert result['motion_windows']['version'] == 1
    with fitness.connect() as db:
        stored = json.loads(db.execute('SELECT payload FROM hrv_sessions').fetchone()['payload'])
        assert stored['motion_windows']['windows'][0]['start_ms'] == 0
    bad = dict(data, motion_windows=dict(windows(), windows=windows()['windows'][:-1]))
    with pytest.raises(ValueError):
        fitness.hrv_ingest(bad)


def test_global_and_window_minimum_coverage_stay_independent(monkeypatch):
    monkeypatch.setenv('HRV_MOTION_POLICIES', json.dumps([
        policy(sample_hz=105, min_coverage=.99, min_window_coverage=.9)
    ]))
    result = motion_quality.assess(payload(motion_windows=windows()))
    assert all(w['nominal_coverage'] >= .9 for w in result['windows'])
    assert result['status'] == 'coverage_insufficient'
    assert result['eligible'] is False


@pytest.mark.parametrize('minimum', [None, True, 0, 1.1])
def test_invalid_global_minimum_not_hidden_by_valid_window_minimum(monkeypatch, minimum):
    monkeypatch.setenv('HRV_MOTION_POLICIES', json.dumps([
        policy(min_coverage=minimum, min_window_coverage=.9)
    ]))
    assert motion_quality.assess(payload(motion_windows=windows()))['status'] == 'invalid_policy'
