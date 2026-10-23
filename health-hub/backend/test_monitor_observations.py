import datetime

import monitor_observations as observations


def ts(day, hour):
    return datetime.datetime(day.year, day.month, day.day, hour, tzinfo=datetime.timezone.utc).timestamp()


def row(at, **payload):
    return {"ts": at, "payload": payload}


def test_reported_hr_survives_rejected_hrv_and_is_not_readiness_input():
    result = observations.build([row(ts(datetime.date(2026, 10, 22), 23), scheduled=True,
                                 reportedHR=52, hr_valid=1, hr_events=1, duration_ms=1000)],
                                now=ts(datetime.date(2026, 10, 23), 8))
    pulse = result["overnight_spot_pulse"][0]
    assert pulse["label"] == "overnight spot pulse"
    assert pulse["pulse"] == 52
    assert pulse["validated"] is False
    assert pulse["proven_resting"] is False
    assert result["readiness_inputs"] == []
    assert result["diagnostics"]["pulse"]["eligible"] == 1


def test_unknown_hr_and_zero_are_excluded_with_reasons():
    result = observations.build([
        row(ts(datetime.date(2026, 10, 22), 23), scheduled=True),
        row(ts(datetime.date(2026, 10, 22), 23), scheduled=True, reportedHR=0),
    ], now=ts(datetime.date(2026, 10, 23), 8))
    assert result["overnight_spot_pulse"] == []
    assert result["diagnostics"]["pulse"]["received"] == 1
    assert result["diagnostics"]["pulse"]["exclusion_reasons"]["reported_hr_invalid"] == 1


def test_rounded_reported_mean_and_integrity_counters_are_accepted():
    result = observations.build([row(ts(datetime.date(2026, 10, 22), 23), scheduled=True,
                                   reportedHR=52.33, hr_valid=3, hr_events=3,
                                   hr_sum=157, duration_ms=1000)],
                                now=ts(datetime.date(2026, 10, 23), 8))
    assert result["overnight_spot_pulse"][0]["pulse"] == 52.3
    assert result["diagnostics"]["pulse"]["eligible"] == 1
    assert "last_measured_at" in result["diagnostics"]["pulse"]
    assert result["diagnostics"]["pulse"]["age_seconds"] == 9 * 3600


def test_future_daytime_and_manual_records_are_excluded():
    now = ts(datetime.date(2026, 10, 23), 8)
    result = observations.build([
        row(now + 3600, scheduled=True, reportedHR=50),
        row(ts(datetime.date(2026, 10, 22), 16), scheduled=True, reportedHR=51),
        row(ts(datetime.date(2026, 10, 22), 23), scheduled=False, reportedHR=52),
    ], now=now)
    reasons = result["diagnostics"]["pulse"]["exclusion_reasons"]
    assert result["overnight_spot_pulse"] == []
    assert reasons["timestamp_invalid_or_future"] == 1
    assert reasons["outside_night_window"] == 1
    assert reasons["context_not_scheduled"] == 1


def test_mixed_methods_choose_comparable_group_and_preserve_actual_timestamps():
    first = ts(datetime.date(2026, 10, 22), 23)
    result = observations.build([
        row(first, scheduled=True, reportedHR=50, reported_hr_method="watch"),
        row(first + 60, scheduled=True, reportedHR=52, reported_hr_method="watch"),
        row(first + 120, scheduled=True, reportedHR=90, reported_hr_method="manual_device"),
    ], now=ts(datetime.date(2026, 10, 23), 8))
    pulse = result["overnight_spot_pulse"][0]
    assert pulse["method"].startswith("watch:")
    assert pulse["pulse"] == 51
    assert pulse["excluded_mixed_methods"] == 1
    assert pulse["observed_at"] == first
    assert result["diagnostics"]["pulse"]["eligible"] == 2
    assert result["diagnostics"]["pulse"]["excluded"] == 1


def test_breathing_and_manual_stress_are_diagnostics_only():
    result = observations.build([
        row(ts(datetime.date(2026, 10, 22), 23), scheduled=True,
            respiration={"breaths_per_min": 14, "reliable": False}, motion_eligible=True),
        row(ts(datetime.date(2026, 10, 22), 10), scheduled=False,
            stress_score=70, stress_status="unknown"),
    ], now=ts(datetime.date(2026, 10, 23), 12))
    assert result["diagnostics"]["breathing"]["eligible"] == 0
    assert result["diagnostics"]["breathing"]["exclusion_reasons"]["insufficient"] == 1
    stress = result["diagnostics"]["stress"]
    assert stress["received_manual_days"] == 1
    assert stress["qualified_manual_days"] == 0
    assert stress["score_used"] is False


def test_bounds_counts_and_spoofed_quality_cannot_qualify():
    now=ts(datetime.date(2026,10,23),12)
    at=ts(datetime.date(2026,10,23),2)
    samples=[row(at,scheduled=True,reportedHR=value,hr_valid=1,hr_events=1) for value in (301,999999,float('inf'),True)]
    samples += [row(at,scheduled=True,reportedHR=50,hr_valid=0,hr_events=1),
                row(at,scheduled=True,reportedHR=50,hr_valid=2,hr_events=1),
                row(at,scheduled=True,reportedHR=50,hr_valid=1,hr_events=1,hr_sum=90)]
    result=observations.build(samples,now=now)
    assert not result['nightly_pulse']
    assert result['diagnostics']['pulse']['eligible']==0
    forged={'respiration':{'reliable':True,'breaths_per_min':15},'motion':{'eligible':True},'stress_status':'experimental','stress_qualified':True}
    result=observations.build([row(at,scheduled=True,**forged),row(at,scheduled=False,**forged),row(now+60,scheduled=True,**forged),row(now+60,scheduled=False,**forged)],now=now)
    assert result['diagnostics']['breathing']['received']==1
    assert result['diagnostics']['breathing']['eligible']==0
    assert result['diagnostics']['stress']['received']==1
    assert result['diagnostics']['stress']['eligible']==0
    assert result['diagnostics']['stress']['qualified_manual_days']==0


def test_half_cent_rounding_boundary_is_not_rejected():
    at=ts(datetime.date(2026,10,23),2)
    result=observations.build([row(at,scheduled=True,mean_reported_hr=52.12,hr_sum=417,hr_valid=8,hr_events=8)],now=at+3600)
    assert result['diagnostics']['pulse']['eligible']==1


def test_briefing_does_not_call_a_past_advertised_slot_next(tmp_path,monkeypatch):
    import fitness,briefing
    from datetime import timezone
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'brief.sqlite3'))
    summary=fitness.summary(7)
    summary['collector']={'next_wakeup':summary['now']-3600}
    assert briefing.facts(summary,timezone.utc)['more']['next_night_recording'] is None
    summary['collector']['next_wakeup']=summary['now']+3600
    assert briefing.facts(summary,timezone.utc)['more']['next_night_recording'] is not None
