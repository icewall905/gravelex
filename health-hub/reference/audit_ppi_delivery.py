#!/usr/bin/env python3
"""Private, offline audit of Pebble PPI delivery semantics.

This intentionally does not alter raw captures or backend classification.  It
compares delivery counters and arrival offsets, while keeping the limitation
explicit that counters cannot establish whether a PPI is a true beat interval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_payload(payload: dict[str, Any], path: Path) -> None:
    ppi = payload.get("ppi")
    offsets = payload.get("offsets_ms")
    if not isinstance(ppi, list) or not isinstance(offsets, list) or len(ppi) != len(offsets) or not ppi:
        raise ValueError(f"{path}: ppi and offsets_ms must be paired non-empty arrays")
    if any(not _finite_number(v) or v <= 0 for v in ppi):
        raise ValueError(f"{path}: PPI values must be finite positive numbers")
    if any(not _finite_number(v) or v < 0 for v in offsets):
        raise ValueError(f"{path}: offsets_ms must be finite non-negative numbers")
    if any(b < a for a, b in zip(offsets, offsets[1:])):
        raise ValueError(f"{path}: offsets_ms must be nondecreasing")
    for key in ("duration_ms", "hr_events", "hr_valid", "hr_sum", "mean_reported_hr"):
        if key in payload and payload[key] is not None and not _finite_number(payload[key]):
            raise ValueError(f"{path}: {key} must be finite when present")


def _least_squares_period(offsets: list[float]) -> float | None:
    """Match backend/hrv.py _sample_period for audit visibility."""
    if len(offsets) < 3:
        return None
    n = len(offsets)
    mean_i = (n - 1) / 2.0
    mean_o = sum(offsets) / n
    denom = sum((i - mean_i) ** 2 for i in range(n))
    return sum((i - mean_i) * (o - mean_o) for i, o in enumerate(offsets)) / denom


def audit_file(path: Path) -> dict[str, Any]:
    envelope = json.loads(path.read_text())
    payload = envelope.get("payload", envelope)
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: payload must be an object")
    _validate_payload(payload, path)
    ppi = payload.get("ppi", [])
    offsets = payload.get("offsets_ms", [])
    positive_gaps = [b - a for a, b in zip(offsets, offsets[1:]) if b > a]
    duplicate_offset_count = 0
    duplicate_group_count = 0
    duplicate_same_value = 0
    duplicate_different_value = 0
    for i in range(1, len(offsets)):
        if offsets[i] != offsets[i - 1]:
            continue
        duplicate_offset_count += 1
        if i == 1 or offsets[i - 2] != offsets[i]:
            duplicate_group_count += 1
        if ppi[i] == ppi[i - 1]:
            duplicate_same_value += 1
        else:
            duplicate_different_value += 1
    duration_ms = payload.get("duration_ms")
    span_ms = max(offsets) - min(offsets) if offsets else None
    hr_valid = payload.get("hr_valid") or 0
    hr_sum = payload.get("hr_sum") or 0
    mean_hr = payload.get("mean_reported_hr")
    if mean_hr is None and hr_valid:
        mean_hr = hr_sum / hr_valid
    hr_beat_estimate = mean_hr * duration_ms / 60000 if mean_hr and duration_ms else None
    same_timestamp_distinct = sum(
        ppi[i] == ppi[i - 1] and offsets[i] != offsets[i - 1]
        for i in range(1, len(ppi))
    )
    runs: list[int] = []
    run = 1
    for i in range(1, len(ppi)):
        if ppi[i] == ppi[i - 1] and offsets[i] != offsets[i - 1]:
            run += 1
        else:
            if run > 1:
                runs.append(run)
            run = 1
    if run > 1:
        runs.append(run)
    return {
        "file": path.name,
        "sha256": _sha256(path),
        "firmware": payload.get("firmware"),
        "collector_version": payload.get("collector_version"),
        "stream_semantics": payload.get("stream_semantics"),
        "context": payload.get("context", "scheduled" if payload.get("scheduled") else "manual"),
        "count": len(ppi),
        "offset_count": len(offsets),
        "duration_ms": duration_ms,
        "offset_min_ms": min(offsets) if offsets else None,
        "offset_max_ms": max(offsets) if offsets else None,
        "positive_gap_count": len(positive_gaps),
        "positive_gap_median_ms": _round(statistics.median(positive_gaps)) if positive_gaps else None,
        "positive_gap_mean_ms": _round(statistics.mean(positive_gaps)) if positive_gaps else None,
        "least_squares_sample_period_ms": _round(_least_squares_period(offsets)),
        "duplicate_offset_count": duplicate_offset_count,
        "duplicate_offset_group_count": duplicate_group_count,
        "duplicate_same_value_count": duplicate_same_value,
        "duplicate_different_value_count": duplicate_different_value,
        "adjacent_identical_ppi_different_timestamp_count": same_timestamp_distinct,
        "adjacent_identical_ppi_run_count": len(runs),
        "longest_adjacent_identical_ppi_run": max(runs, default=1),
        "unique_ppi_count": len(set(ppi)),
        "raw_ppi_sum_ms": sum(ppi),
        "raw_ppi_sum_over_duration": _round(sum(ppi) / duration_ms, 4) if duration_ms else None,
        "raw_ppi_sum_over_offset_span": _round(sum(ppi) / span_ms, 4) if span_ms else None,
        "hr_events": payload.get("hr_events"),
        "hr_valid": hr_valid,
        "hr_sum_bpm": hr_sum,
        "mean_reported_hr_bpm": _round(mean_hr, 3) if mean_hr is not None else None,
        "reported_hr_based_beat_estimate": _round(hr_beat_estimate, 3),
        "event_to_hr_beat_estimate_ratio": _round(payload.get("hr_events") / hr_beat_estimate, 4)
        if payload.get("hr_events") is not None and hr_beat_estimate else None,
    }


def make_report(data_dir: Path) -> dict[str, Any]:
    files = sorted(data_dir.glob("*watch.json"))
    rows = [audit_file(path) for path in files]
    semantics = sorted({r["stream_semantics"] for r in rows})
    collector_versions = sorted({r["collector_version"] for r in rows})
    periods = [r["positive_gap_median_ms"] for r in rows if r["positive_gap_median_ms"] is not None]
    ls_periods = [r["least_squares_sample_period_ms"] for r in rows if r["least_squares_sample_period_ms"] is not None]
    source_path = data_dir.parent / "watchapps/hrv-watch/src/c/main.c"
    low_hr = [r for r in rows if r.get("mean_reported_hr_bpm") is not None and r["mean_reported_hr_bpm"] <= 55]
    high_hr = [r for r in rows if r.get("mean_reported_hr_bpm") is not None and r["mean_reported_hr_bpm"] >= 70]
    def group_summary(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "file_count": len(group),
            "files": [r["file"] for r in group],
            "mean_hr_bpm": _round(statistics.mean(r["mean_reported_hr_bpm"] for r in group), 2) if group else None,
            "mean_ppi_count": _round(statistics.mean(r["count"] for r in group), 2) if group else None,
            "mean_raw_ppi_sum_over_duration": _round(statistics.mean(r["raw_ppi_sum_over_duration"] for r in group), 4) if group else None,
            "identical_ppi_different_timestamp_transitions": sum(r["adjacent_identical_ppi_different_timestamp_count"] for r in group),
            "longest_identical_ppi_run": max((r["longest_adjacent_identical_ppi_run"] for r in group), default=1),
        }
    return {
        "report": "ppi-delivery-audit",
        "report_version": 1,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "privacy": "private raw-recording audit; no raw PPI values copied into this report",
        "scope": {
            "directory": str(data_dir),
            "glob": "*watch.json",
            "file_count": len(rows),
            "files": [r["file"] for r in rows],
            "archives_excluded": True,
            "reason_archives_excluded": "Archives duplicate named captures; top-level reference-data files are the canonical copies.",
        },
        "method": {
            "raw_ppi_sum": "sum of delivered PPI array values, compared with declared duration and offset span",
            "reported_hr_beats": "mean_reported_hr_bpm * duration_ms / 60000; hr_events is a callback/event counter, not a beat counter",
            "batching": "duplicate offsets counted and split by adjacent PPI value equality",
            "cadence": "positive offset gaps only; duplicate offsets are excluded from gap statistics",
            "classification_reference": "backend/hrv.py _sample_period is least-squares offset-vs-index slope; latest_ppi_updates forces tachogram classification",
            "firmware_capture_source": "on_health() calls health_service_peek_hrv_ppi_ms() once per HealthEventHRVUpdate and appends one value with elapsed() offset; this collector source does not prove physiological beat continuity or expose upstream algorithm internals",
        },
        "findings": {
            "stream_semantics_values": semantics,
            "collector_versions": collector_versions,
            "all_latest_ppi_updates": all(r["stream_semantics"] == "latest_ppi_updates" for r in rows),
            "median_positive_gap_ms_min": min(periods) if periods else None,
            "median_positive_gap_ms_max": max(periods) if periods else None,
            "median_positive_gap_ms_median": _round(statistics.median(periods)) if periods else None,
            "least_squares_sample_period_ms_min": min(ls_periods) if ls_periods else None,
            "least_squares_sample_period_ms_max": max(ls_periods) if ls_periods else None,
            "low_hr_group_le_55_bpm": group_summary(low_hr),
            "high_hr_group_ge_70_bpm": group_summary(high_hr),
            "low_hr_vs_high_hr_note": "Low-HR captures around 53 bpm can have 175 delivered PPIs whose sum/duration is about 1.19, while a high-HR prospective capture has 211 PPIs and sum/duration about 0.967. This is a delivery/sampling consistency contrast, not proof of missing or continuous beats.",
            "classification": "all captures are routed to rmssd_1hz_tachogram_reconstructed by current hrv.py semantics",
            "one_hz_status": "not established as a physiological sample clock",
            "delivery_cadence": "approximately 1-second positive offset gaps support a roughly 1-second delivery/batch cadence; latest_ppi_updates is a source/model tag used by the classifier, not independent proof that PPI values are periodic samples or true consecutive beats",
            "beat_vs_tachogram_ambiguity": "PPI count, HR event count, HR-derived beat estimate, and PPI sum are delivery/summary counters. They cannot prove that each PPI is a consecutive measured beat interval; preserve source ambiguity.",
            "duplicate_value_ambiguity": "duplicate offsets with different PPI values demonstrate batching/coalesced updates in the transport; they do not by themselves establish whether values are beat intervals or latest sampled RR values.",
        },
        "provenance": {
            "payload_method": "Pebble watch hrv-watch collector payload: ppi and offsets_ms emitted by watch, stream_semantics set by phone bridge",
            "source": str(source_path),
            "source_sha256": _sha256(source_path),
            "source_claim": "The checked-in collector source confirms one peeked PPI per HRV callback; no source in this repository confirms that a callback contains up to four RRI values.",
            "raw_file_hashes": {r["file"]: r["sha256"] for r in rows},
            "audit_script": "reference/audit_ppi_delivery.py",
        },
        "sessions": rows,
        "limits": [
            "No ECG/chest-strap beat timestamps are present, so true beat coverage is unvalidated.",
            "Reported HR fields are sampled callback summaries; hr_events is not interpreted as beats.",
            "Offset timestamps are arrival/delivery offsets and may contain batching duplicates.",
            "No deduplication, smoothing, calibration, or backend/raw data mutation was performed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = make_report(args.data_dir)
    encoded = (json.dumps(report, indent=2, allow_nan=False) + "\n").encode()
    fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(encoded)


if __name__ == "__main__":
    main()
