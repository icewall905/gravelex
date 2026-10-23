"""Synthetic contracts for delivery-batched PPI analysis."""
import math
import json
from datetime import datetime, timezone

import hrv
import pytest


def capture(ppi=None, offsets=None, **extra):
    if ppi is None:
        ppi = [900 + (i % 3) * 10 for i in range(121)]
    if offsets is None:
        offsets = [30_000 + i * 1000 for i in range(len(ppi))]
    return {"ppi": ppi, "offsets_ms": offsets, "stream_semantics": "batched_ppi_unverified",
            "scheduled": True, "motion_samples": 3001, "motion_total": 3000,
            "motion_source": "raw_accelerometer", "firmware": "synthetic",
            "collector_version": 1, **extra}


def test_batched_output_is_delivery_only_and_keeps_raw_records():
    result = hrv.analyze_session(capture([900, 910, 920, 930], [30_000, 30_000, 31_000, 31_000]))
    assert result["stream"] == "batched_ppi_unverified"
    assert result["metric"] == "delivered_ppi_variation_unverified"
    assert result["algorithm_version"] == "hrv-v3-batched-ppi"
    assert result["validated"] is False
    assert result["diagnostic_rmssd_ms"] is None
    assert result["experimental_rmssd_ms"] is None
    assert result["respiration"] is None
    assert [x["ppi_ms"] for x in result["cleaned_intervals"]] == [900, 910, 920, 930]
    assert result["delivery"]["batch_count"] == 2
    assert result["delivery"]["max_batch_size"] == 2
    assert result["delivery"]["total_delivered"] == 4
    assert result["delivery"]["clock"] == "arrival_time_only"
    assert result["cadence_consistent"] is None and result["sample_period_ms"] is None
    assert result["source"] == "pebble_ppi:firmware=synthetic:collector=1"


def test_equal_offset_different_values_are_not_deduplicated():
    result = hrv.analyze_session(capture([900, 910, 920], [30_000, 30_000, 30_000]))
    assert result["original_count"] == result["retained_count"] == 3
    assert result["delivered_adjacent_pairs"] == 2
    assert result["delivery"]["equal_offset_different_value_pairs"] == 2


def test_reject_and_large_gap_split_delivered_adjacent_pairs():
    result = hrv.analyze_session(capture([900, 900, 100, 910, 920], [30_000, 31_000, 32_000, 33_000, 38_001]))
    assert result["delivered_adjacent_pairs"] == 1
    assert result["consecutive_pairs"] == 0
    assert "rejected_sample_splits_delivery_run" in result["reasons"]
    assert "oversized_arrival_gap" in result["reasons"]


def test_reverse_offsets_are_insufficient_and_never_a_clock():
    result = hrv.analyze_session(capture(ppi=[900] * 61,
                                         offsets=[30_000 + i * 1000 for i in range(60)] + [30_500]))
    assert result["status"] == "insufficient"
    assert result["sample_period_ms"] is None
    assert "nonmonotonic_arrival_times" in result["reasons"]


@pytest.mark.parametrize("bad", [[math.nan, 900], ["900", 900], [True, 900]])
def test_malformed_batched_numbers_fail_closed(bad):
    with pytest.raises(ValueError):
        hrv.analyze_session(capture(ppi=bad, offsets=[30_000, 31_000]))


@pytest.mark.parametrize("count", [0, 1, 2])
def test_short_batched_payload_has_no_clock_and_is_json_safe(count):
    result = hrv.analyze_session(capture(ppi=[900] * count,
                                         offsets=[30_000 + i * 1000 for i in range(count)]))
    assert result["delivery"]["offset_index_slope_ms"] is None
    assert result["sample_period_ms"] is None
    assert result["validated"] is False
    json.dumps(result, allow_nan=False)


def test_batched_history_never_builds_stress_baseline_even_after_14_days():
    now = datetime(2026, 10, 23, tzinfo=timezone.utc).timestamp()
    rows = [{"ts": now - i * 86400, "payload": capture()} for i in range(15)]
    result = hrv.analyze_history(rows, now=now)
    assert result["baseline_progress"]["scheduled"]["adequate_baseline_days"] == 0
    assert result["stress"]["status"] == "quality_insufficient"
    assert "beat continuity is unverified" in result["stress"]["reason"]
    assert result["stress"]["experimental_score"] is None


def test_legacy_untagged_fixture_stays_on_legacy_path():
    payload = capture()
    payload.pop("stream_semantics")
    result = hrv.analyze_session(payload)
    assert result["algorithm_version"] == "hrv-v2-motion"
    assert result["stream"] != "batched_ppi_unverified"
