#!/usr/bin/env python3
"""Offline audit of one BLE RR JSONL capture and one Pebble PPI record.

This is an evidence report only.  It never uploads data, calibrates the watch,
or enables a score.  Arrival times are treated as receipt times and are never
claimed to be beat timestamps.
"""
from __future__ import annotations

import argparse
import importlib.util
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

from ble_rr import segmented_diagnostics

GAP_SECONDS = 5.0
DUPLICATE_WINDOW_SECONDS = 0.25
WATCH_WARMUP_SECONDS = 30.0


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _packet_identity(row: dict[str, Any]) -> str:
    """Stable raw-packet identity, including a useful fixture fallback."""
    if row.get("packet_hex") is not None:
        return str(row["packet_hex"])
    return json.dumps({key: row.get(key) for key in ("flags", "heart_rate_bpm", "rr_ticks", "rr_ms")},
                      sort_keys=True, separators=(",", ":"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: expected JSON object")
        rows.append(value)
    return rows


def _load_watch(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or not isinstance(value.get("payload"), dict):
        raise ValueError("watch file must contain {ts, payload}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _watch_window(watch: dict[str, Any]) -> tuple[float, float]:
    payload = watch["payload"]
    ts = watch.get("ts")
    offsets = payload.get("offsets_ms", [])
    if (not _finite(ts) or not isinstance(offsets, list) or len(offsets) < 2 or
            not all(_finite(v) and float(v) >= 0 for v in offsets)):
        raise ValueError("watch file needs finite ts and offsets_ms")
    start, end = float(ts) + min(offsets) / 1000.0, float(ts) + max(offsets) / 1000.0
    if end <= start:
        raise ValueError("watch offsets_ms must span a positive window")
    return start, end


def _raw_audit(rows: list[dict[str, Any]], window: tuple[float, float] | None = None) -> tuple[dict[str, Any], list[list[float]], tuple[float, float] | None]:
    measurements = [r for r in rows if r.get("type") in ("measurement", "parse_error")]
    receipt_rows = [r for r in measurements if _finite(r.get("received_at"))]
    receipt_rows.sort(key=lambda r: float(r["received_at"]))
    all_times = [float(r["received_at"]) for r in receipt_rows]
    if window is not None:
        receipt_rows = [r for r in receipt_rows if window[0] <= float(r["received_at"]) <= window[1]]
    times = [float(r["received_at"]) for r in receipt_rows]
    segments: list[list[float]] = [[]]
    missing_rr = 0
    invalid_rr = 0
    gap_count = 0
    raw_intervals: list[float] = []
    all_intervals: list[float] = []
    contact_off_count = 0
    for index, row in enumerate(receipt_rows):
        if index and times[index] - times[index - 1] > GAP_SECONDS:
            gap_count += 1
            segments.append([])
        values = row.get("rr_ms")
        contact_off = row.get("contact_detected") is False
        parse_error = row.get("type") == "parse_error"
        valid = isinstance(values, list) and all(_finite(v) and float(v) > 0 for v in values)
        if not values or parse_error:
            missing_rr += 1
            segments.append([])
            continue
        if not valid:
            invalid_rr += 1
            segments.append([])
            continue
        numbers = [float(v) for v in values]
        all_intervals.extend(numbers)
        if contact_off:
            contact_off_count += 1
            segments.append([])
        else:
            raw_intervals.extend(numbers)
            segments[-1].extend(numbers)
    duplicates = []
    for left, right in zip(receipt_rows, receipt_rows[1:]):
        dt = float(right["received_at"]) - float(left["received_at"])
        if dt <= DUPLICATE_WINDOW_SECONDS and _packet_identity(left) == _packet_identity(right):
            duplicates.append({"left_sequence": left.get("sequence"), "right_sequence": right.get("sequence"),
                               "delta_seconds": round(dt, 6), "packet_hex": left.get("packet_hex"),
                               "identity": _packet_identity(left)})
    duration = times[-1] - times[0] if len(times) > 1 else 0.0
    sum_rr = sum(all_intervals)
    summary = next((r for r in rows if r.get("type") == "summary"), {})
    ratio_flag = sum_rr / 1000.0 > duration * 1.2 if duration else False
    flags = sorted(set((['missing_rr_packets'] if missing_rr else []) +
                       (['invalid_rr_packets'] if invalid_rr else []) +
                       (['contact_false_packets'] if contact_off_count else []) +
                       (['receipt_gaps'] if gap_count else []) +
                       (['rapid_identical_packets'] if duplicates else []) +
                       (['rr_sum_exceeds_receipt_duration'] if ratio_flag else []) +
                       (['earlydisconnect'] if summary.get('recording_completed') is False and summary else [])))
    bpm = [float(r["heart_rate_bpm"]) for r in receipt_rows if _finite(r.get("heart_rate_bpm"))]
    return ({"measurement_count": len(measurements), "receipt_timestamp_count": len(receipt_rows),
             "all_receipt_timestamp_count": len(all_times),
             "rr_packet_count": sum(1 for r in receipt_rows if r.get("rr_ms")),
             "rr_interval_count": len(all_intervals), "diagnostic_rr_interval_count": len(raw_intervals), "sum_rr_ms": round(sum_rr, 6),
             "receipt_duration_seconds": round(duration, 6),
             "sum_rr_over_receipt_duration": round((sum_rr / 1000.0) / duration, 6) if duration else None,
             "heart_rate_mean_bpm": round(sum(bpm) / len(bpm), 3) if bpm else None,
             "heart_rate_median_bpm": round(sorted(bpm)[len(bpm) // 2] if len(bpm) % 2 else
                                             (sorted(bpm)[len(bpm)//2-1] + sorted(bpm)[len(bpm)//2]) / 2, 3) if bpm else None,
             "missing_rr_packet_count": missing_rr, "invalid_rr_packet_count": invalid_rr,
             "contact_false_packet_count": contact_off_count,
             "gap_count": gap_count, "gaps_over_seconds": GAP_SECONDS,
             "duplicate_rapid_identical_packet_count": len(duplicates), "duplicate_packets": duplicates,
             "recording_completed": summary.get("recording_completed"),
             "error": summary.get("error"), "error_stage": summary.get("error_stage"),
             "diagnostic": segmented_diagnostics(segments), "flags": flags},
            segments, (times[0], times[-1]) if times else None)


def _watch_quality(payload: dict[str, Any]) -> dict[str, Any]:
    backend = Path(__file__).resolve().parents[1] / "backend" / "hrv.py"
    spec = importlib.util.spec_from_file_location("pebble_backend_hrv", backend)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {backend}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(backend.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module.analyze_session(payload)


def analyze_pair(reference_path: Path | str, watch_path: Path | str,
                 latency_uncertainty_seconds: float = 2.0) -> dict[str, Any]:
    if not _finite(latency_uncertainty_seconds) or latency_uncertainty_seconds < 0:
        raise ValueError("latency uncertainty must be finite and non-negative")
    rows = _load_jsonl(Path(reference_path))
    watch = _load_watch(Path(watch_path))
    raw, _, raw_window = _raw_audit(rows)
    watch_start, watch_end = _watch_window(watch)
    overlap = None
    if raw_window:
        raw_start, raw_end = raw_window
        exact_start, exact_end = max(raw_start, watch_start), min(raw_end, watch_end)
        # A receipt may be delayed relative to the source clock.  Report both
        # the observed intersection and a conservative interval widened by the
        # declared uncertainty; never turn uncertainty into qualification.
        guaranteed_seconds = max(0.0, exact_end - exact_start - 2.0 * latency_uncertainty_seconds)
        overlap = {"observed_receipt_overlap_seconds": round(max(0.0, exact_end - exact_start), 6),
                   "overlap_lower_bound_under_assumed_latency_seconds": round(guaranteed_seconds, 6),
                   "raw_window": [raw_start, raw_end], "watch_window": [watch_start, watch_end],
                   "latency_uncertainty_seconds": latency_uncertainty_seconds,
                   "latency_uncertainty_basis": "user-supplied assumption; not measured",
                   "timestamp_basis": "raw received_at and watch ts+offsets_ms; receipt times are not beat timestamps"}
    paired_raw = _raw_audit(rows, (watch_start, watch_end))[0]
    post_warmup_raw = _raw_audit(rows, (watch_start + WATCH_WARMUP_SECONDS, watch_end))[0]
    watch_diag = _watch_quality(watch["payload"])
    flags = list(raw["flags"])
    if raw.get("recording_completed") is None:
        flags.append("summary_missing_or_incomplete")
    elif raw.get("recording_completed") is False:
        flags.append("summary_missing_or_incomplete")
    if raw_window is None or overlap is None or overlap["observed_receipt_overlap_seconds"] <= 0:
        flags.append("nonoverlap")
    elif overlap["overlap_lower_bound_under_assumed_latency_seconds"] <= 0:
        flags.append("overlap_below_assumed_latency_bound")
    if overlap and overlap["observed_receipt_overlap_seconds"] + 1e-6 < watch_end - watch_start:
        flags.append("partial_watch_coverage")
    if raw["duplicate_rapid_identical_packet_count"]:
        flags.append("duplicate_rapid_identical_packets")
    if watch_diag.get("status") == "insufficient" or watch_diag.get("span_ms", 0) < (watch_end - watch_start) * 1000 * 0.5:
        flags.append("insufficient_watch_coverage")
    if raw.get("recording_completed") is False:
        flags.append("earlydisconnect")
    watch_mean = watch["payload"].get("mean_reported_hr")
    if _finite(watch_mean):
        raw["watch_reported_mean_hr_bpm"] = round(float(watch_mean), 3)
        ref_mean = paired_raw.get("heart_rate_mean_bpm")
        ref_median = paired_raw.get("heart_rate_median_bpm")
        raw["watch_vs_reference_mean_delta_bpm"] = round(float(watch_mean) - ref_mean, 3) if _finite(ref_mean) else None
        raw["watch_vs_reference_median_delta_bpm"] = round(float(watch_mean) - ref_median, 3) if _finite(ref_median) else None
    return {"format_version": 1, "qualified": False, "calibration_enabled": False, "score_enabled": False,
            "reference": raw, "paired_window_reference": paired_raw, "post_warmup_reference": post_warmup_raw,
            "watch": {"diagnostics": watch_diag, "window": [watch_start, watch_end],
                      "warmup_seconds": WATCH_WARMUP_SECONDS,
                      "warmup_note": "backend/hrv excludes the first 30 seconds as warmup; this is separate from paired receipt overlap."},
            "overlap": overlap, "flags": sorted(set(flags)),
            "reproducibility": {"reference_sha256": _sha256(Path(reference_path)),
                                 "watch_sha256": _sha256(Path(watch_path)),
                                 "analyzer_sha256": _sha256(Path(__file__)),
                                 "watch_firmware": watch["payload"].get("firmware"),
                                 "watch_collector_version": watch["payload"].get("collector_version")},
            "notes": ["Offline audit only; no upload, calibration, or score is enabled.",
                      "Raw duplicate packets are retained and counted; no silent deduplication.",
                      "RMSSD is segmented at missing RR packets and receipt gaps; no interpolation is used."]}


def _write_exclusive(path: Path, report: dict[str, Any]) -> None:
    data = (json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        fd = -1
    finally:
        if fd >= 0:
            os.close(fd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference_jsonl", type=Path)
    parser.add_argument("watch_json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--latency-uncertainty", type=float, default=2.0)
    args = parser.parse_args()
    report = analyze_pair(args.reference_jsonl, args.watch_json, args.latency_uncertainty)
    _write_exclusive(args.output, report)
    print(json.dumps({"output": str(args.output), "qualified": False, "flags": report["flags"]}))


if __name__ == "__main__":
    main()
