"""Synthetic calibration fixtures exercise gates, not real physiological thresholds."""
import json
import math
import pytest
import motion_quality
import hrv


def capture(**overrides):
    return dict({'motion_samples':4501,'motion_total':4500,'motion_source':'raw_accelerometer',
                 'firmware':'test-fw','collector_version':150,'vibration_status':'unknown',
                 'offsets_ms':[i*1000 for i in range(181)],
                 'ppi':[int(900+20*math.sin(i/5)) for i in range(181)],
                 'stream_semantics':'latest_ppi_updates','scheduled':True}, **overrides)


@pytest.fixture
def calibrated(monkeypatch):
    policy={'id':'synthetic-test-only','evidence':'unit-test-fixture-not-real-calibration',
            'source':'raw_accelerometer','firmware':'test-fw','collector_version':150,
            'sample_hz':25,'max_mean_delta':2,'min_coverage':0.9}
    monkeypatch.setenv('HRV_MOTION_POLICIES',json.dumps([policy]))
    return policy


def test_no_default_calibration_or_trust_in_uploaded_threshold(monkeypatch):
    monkeypatch.delenv('HRV_MOTION_POLICIES',raising=False)
    result=hrv.analyze_session(capture(max_mean_delta=10000,calibrated=True))
    assert result['status']=='motion_uncalibrated'
    assert result['experimental_rmssd_ms'] is None
    assert result['diagnostic_rmssd_ms'] is not None
    assert result['motion']['eligible'] is False


def test_calibrated_quiet_passes_and_high_motion_does_not(calibrated):
    quiet=hrv.analyze_session(capture())
    moving=hrv.analyze_session(capture(motion_total=45000))
    assert quiet['status']=='experimental'
    assert quiet['experimental_rmssd_ms'] is not None
    assert moving['status']=='motion_excessive'
    assert moving['experimental_rmssd_ms'] is None
    assert moving['respiration'] is None
    assert moving['motion']['normalized_mean']==10


@pytest.mark.parametrize('change,expected', [
    ({'motion_samples':10},'coverage_insufficient'),
    ({'motion_samples':100000},'coverage_inconsistent'),
    ({'firmware':'other-fw'},'uncalibrated'),
    ({'motion_source':'processed_accelerometer'},'uncalibrated'),
    ({'collector_version':151},'uncalibrated'),
    ({'motion_samples':False},'missing'),
    ({'motion_total':float('nan')},'missing'),
    ({'vibration_samples':2},'vibration'),
])
def test_motion_mismatch_or_incomplete_capture_is_not_eligible(calibrated,change,expected):
    result=motion_quality.assess(capture(**change))
    assert result['status']==expected
    assert result['eligible'] is False


@pytest.mark.parametrize('value',['invalid','{}','[{}]'])
def test_invalid_configuration_never_passes(monkeypatch,value):
    monkeypatch.setenv('HRV_MOTION_POLICIES',value)
    assert motion_quality.assess(capture())['eligible'] is False


def test_ambiguous_or_bad_matching_policy_fails_closed(monkeypatch,calibrated):
    monkeypatch.setenv('HRV_MOTION_POLICIES',json.dumps([calibrated,calibrated]))
    assert motion_quality.assess(capture())['status']=='invalid_policy'
    calibrated['max_mean_delta']=True
    monkeypatch.setenv('HRV_MOTION_POLICIES',json.dumps([calibrated]))
    assert motion_quality.assess(capture())['status']=='invalid_policy'


def test_history_cannot_use_uncalibrated_or_cross_source_baseline(monkeypatch,calibrated):
    import time
    now=int(time.time())
    rows=[{'ts':now-i*86400,'payload':capture()} for i in range(16)]
    assert hrv.analyze_history(rows)['stress']['experimental_score'] is not None
    rows[0]['payload']['firmware']='other-fw'
    result=hrv.analyze_history(rows)
    assert result['stress']['experimental_score'] is None
    assert result['stress']['baseline_days']==0


def test_future_and_invalid_timestamps_do_not_select_current_or_build_baseline(calibrated):
    now=1792680000
    past=[{'ts':now-i*86400,'payload':capture()} for i in range(16)]
    future=[{'ts':now+86400,'payload':capture(firmware='other-fw')},
            {'ts':float('nan'),'payload':capture()}, {'ts':1e100,'payload':capture()}]
    result=hrv.analyze_history(past+future,now=now)
    assert result['stress']['measured_at']==now
    assert result['stress']['baseline_days']==15
    assert result['stress']['experimental_score'] is not None
    assert hrv.analyze_history(future,now=now)['stress']['experimental_score'] is None


def test_old_stress_is_historical_and_progress_counts_distinct_matching_prior_days(calibrated,monkeypatch):
    now=1792680000
    rows=[{'ts':now-i*86400,'payload':capture()} for i in range(16)]
    # Another collector on the same day must not inflate this collector's progress.
    other=dict(calibrated,collector_version=151,id='other-test-policy')
    monkeypatch.setenv('HRV_MOTION_POLICIES',json.dumps([calibrated,other]))
    rows += [{'ts':now-i*86400-1,'payload':capture(collector_version=151)} for i in range(16)]
    result=hrv.analyze_history(rows,now=now)
    assert result['baseline_progress']['scheduled']['adequate_baseline_days']==15
    assert result['stress']['baseline_days']==15
    assert result['stress']['expires_at']==now+36*3600
    stale=hrv.analyze_history(rows,now=now+36*3600+1)['stress']
    assert stale['status']=='stale'
    assert stale['experimental_score'] is None
    assert stale['measured_at']==now
    manual=[{'ts':now,'payload':capture(scheduled=False)}]
    assert hrv.analyze_history(manual,now=now+4*3600+1)['stress']['status']=='stale'
