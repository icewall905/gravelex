"""Downstream consumers keep batched PPI diagnostic-only."""
from datetime import date, datetime, timezone

import briefing
import hrv
import monitor_observations
import recovery


def _payload(context="scheduled"):
    offsets = [30_000 + i * 1_000 for i in range(80)]
    return {
        "ppi": [900 + (i % 3) for i in range(80)],
        "offsets_ms": offsets,
        "context": context,
        "scheduled": context == "scheduled",
        "reportedHR": 52,
        "hr_valid": 1,
        "hr_events": 1,
        "duration_ms": offsets[-1],
        "stream_semantics": "batched_ppi_unverified",
        "motion_windows": [],
    }


def test_batched_quality_is_never_a_recovery_night():
    quality = hrv.analyze_session(_payload())
    assert quality["status"] == "beat_continuity_unverified"
    assert quality["diagnostic_rmssd_ms"] is None
    assert quality["diagnostic_delivered_ppi_variation_ms"] is not None
    assert recovery.nightly_hrv([(datetime(2026, 10, 22, 23, tzinfo=timezone.utc).timestamp(), quality)]) == []


def test_batched_monitor_counts_delivery_failure_but_keeps_pulse():
    at = datetime(2026, 10, 22, 23, tzinfo=timezone.utc).timestamp()
    now = datetime(2026, 10, 23, 8, tzinfo=timezone.utc).timestamp()
    scheduled = _payload()
    manual = _payload("manual")
    result = monitor_observations.build(
        [{"ts": at, "payload": scheduled}, {"ts": at, "payload": manual}], now=now
    )
    assert result["overnight_spot_pulse"][0]["pulse"] == 52
    assert result["diagnostics"]["breathing"]["exclusion_reasons"]["beat_continuity_unverified"] == 1
    assert result["diagnostics"]["stress"]["exclusion_reasons"]["beat_continuity_unverified"] == 1
    assert result["diagnostics"]["breathing"]["eligible"] == 0
    assert result["diagnostics"]["stress"]["eligible"] == 0


def test_briefing_exposes_bounded_delivery_diagnostic():
    summary = {"now": datetime(2026, 10, 23, 8, tzinfo=timezone.utc).timestamp(),
               "hrv": {"quality": {"status": "beat_continuity_unverified",
                                    "metric": "delivered_ppi_variation_unverified",
                                    "stream": "batched_ppi_unverified",
                                    "diagnostic_delivered_ppi_variation_ms": 4.2,
                                    "delivery": {"total_delivered": 80}}},
               "recovery": {}, "latest": {}, "collection_health": {}, "fitness": {},
               "weight": {}, "oxygen": {}, "stress": {}, "training": {}, "history": [],
               "observations": [], "collector": {}, "monitor_observations": {}}
    facts = briefing.facts(summary, timezone.utc)["recovery"]
    assert "diagnostic_delivered_ppi_variation_ms" not in facts["hrv_capture_quality"]
    assert facts["hrv_source_blocked_reason"]
