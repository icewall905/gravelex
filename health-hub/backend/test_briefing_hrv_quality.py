from datetime import datetime, timezone
import briefing
import fitness


def test_llm_facts_do_not_pool_series_and_preserve_exclusion_context(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'facts.sqlite3'))
    summary=fitness.summary(7)
    summary['now']=int(datetime(2026,10,22,12,tzinfo=timezone.utc).timestamp())
    identity={'metric':'tachogram','source':'collector151','algorithm_version':'v2'}
    summary['recovery']['hrv_status']['comparable_series']=identity
    def night(day,value,series):
        return {'night':day,'rmssd_ms':value,'resting_hr':60,'sessions':1,
                'breaths_per_min':None,'comparable_series':series}
    summary['recovery']['nights']=[night('2026-10-20',30,identity),night('2026-10-21',90,dict(identity,source='other')),
                                  night('2026-10-22',35,identity),night('2026-10-23',100,identity)]
    summary['hrv']['quality']={'status':'motion_uncalibrated','motion':{'reason':'No matching calibration'}}
    summary['stress']={'status':'stale','measured_at':123,'reason':'Historical observation'}
    result=briefing.facts(summary,timezone.utc)['recovery']
    assert result['hrv_avg_previous_nights_ms']==30
    assert result['hrv_previous_nights_in_avg']==1
    assert result['hrv_capture_quality']['status']=='motion_uncalibrated'
    assert result['stress_observation']['reason']=='Historical observation'
