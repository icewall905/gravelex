"""Recovery comparisons require the same measurement method and producer."""
from datetime import date, datetime, timedelta
import math
import recovery
TODAY = date(2026, 10, 22)

def session(day=TODAY, metric='beat', source='watch-a', version='v2', value=40):
    q = dict(context='scheduled', status='experimental', experimental_rmssd_ms=value,
             mean_rr_ms=1000, metric=metric)
    if source is not None: q['source'] = source
    if version is not None: q['algorithm_version'] = version
    return datetime.combine(day, datetime.min.time(), recovery.TZ).timestamp() + 10800, q

def night(day, **kwargs):
    return recovery.nightly_hrv([session(day, **kwargs)])[0]

def test_mixed_night_selects_dominant_without_averaging():
    n = recovery.nightly_hrv([session(), session(), session(metric='tachogram', value=400)])[0]
    assert n['rmssd_ms'] == 40 and n['sessions'] == 2 and n['excluded_sessions'] == 1
    assert n['excluded_groups'][0]['reason'] == 'incompatible_measurement_series'

def test_tie_is_independent_of_upload_order():
    data = [session(source='b', value=400), session(source='a')]
    assert recovery.nightly_hrv(data) == recovery.nightly_hrv(list(reversed(data)))
    assert recovery.nightly_hrv(data)[0]['rmssd_ms'] == 40

def test_producer_and_algorithm_are_not_averaged():
    for changed in [dict(source='other'), dict(version='v3')]:
        n = recovery.nightly_hrv([session(), session(**changed, value=400)])[0]
        assert n['sessions'] == 1 and n['excluded_sessions'] == 1
        assert n['rmssd_ms'] in (40, 400)

def test_source_or_version_change_resets_both_baselines():
    for changed in [dict(source='new-watch'), dict(version='v3')]:
        data = [night(TODAY-timedelta(days=i)) for i in range(1,30)] + [night(TODAY, **changed)]
        status = recovery.hrv_status(data, TODAY)
        ready = recovery.readiness(data, {}, None, TODAY)
        assert status['status'] == 'baseline_building' and status['baseline_nights'] == 0
        assert 'hrv' not in ready['components'] and 'resting_hr' not in ready['components']
        assert any('resting_hr: baseline building (0' in x for x in ready['missing'])

def test_future_cannot_select_series_or_hide_today():
    data = [night(TODAY-timedelta(days=i)) for i in range(29,-1,-1)]
    future = night(TODAY+timedelta(days=1), source='future')
    assert recovery.hrv_status([future]+data, TODAY) == recovery.hrv_status(data, TODAY)
    assert recovery.readiness(data+[future], {}, None, TODAY) == recovery.readiness(data, {}, None, TODAY)

def test_legacy_homogeneous_fixtures_work_but_do_not_mix():
    data = [dict(night=(TODAY-timedelta(days=i)).isoformat(), metric='beat', rmssd_ms=40,
                 ln_rmssd=math.log(40), resting_hr=60) for i in range(29,-1,-1)]
    assert recovery.hrv_status(data, TODAY)['status'] == 'balanced'
    assert 'resting_hr' in recovery.readiness(data, {}, None, TODAY)['components']
    data[-1] = night(TODAY)
    assert recovery.hrv_status(data, TODAY)['baseline_nights'] == 0
    assert not recovery.readiness(data, {}, None, TODAY)['components']
