#!/usr/bin/env python3
"""Offline diagnostic comparison of an observed breath count and watch PPI."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from pathlib import Path
from typing import Any


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value, hashlib.sha256(raw).hexdigest()


def _load_hrv():
    path = Path(__file__).resolve().parents[1] / "backend" / "hrv.py"
    spec = importlib.util.spec_from_file_location("pebble_breathing_hrv", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module, hashlib.sha256(path.read_bytes()).hexdigest()


def analyze_breathing(watch_path: Path | str, annotation_path: Path | str) -> dict[str, Any]:
    watch_path, annotation_path = Path(watch_path), Path(annotation_path)
    watch, watch_sha = _read_json(watch_path)
    annotation, annotation_sha = _read_json(annotation_path)
    payload = watch.get("payload")
    if not isinstance(payload, dict) or not _finite(watch.get("ts")):
        raise ValueError("watch file must contain finite ts and payload")
    capture = annotation.get("capture")
    if not isinstance(capture, dict) or capture.get("sha256") != watch_sha:
        raise ValueError("annotation capture sha256 does not match watch input")
    count = annotation.get("observed_breath_count")
    window = annotation.get("observed_breath_window")
    if (isinstance(count, bool) or not isinstance(count, int) or count < 0 or
            not isinstance(window, list) or len(window) != 2 or not all(_finite(v) for v in window)):
        raise ValueError("annotation needs a nonnegative observed count and finite two-value window")
    start, end = float(window[0]), float(window[1])
    if end <= start or end - start < 60.0:
        raise ValueError("observed breathing window must be at least 60 seconds")
    ts = float(watch["ts"])
    offsets = payload.get("offsets_ms")
    if (not isinstance(offsets, list) or not offsets or
            not all(_finite(x) and float(x) >= 0 for x in offsets)):
        raise ValueError("watch payload needs finite offsets_ms")
    capture_start, capture_end = ts + min(offsets) / 1000.0, ts + max(offsets) / 1000.0
    if start < capture_start or end > capture_end:
        raise ValueError("observed breathing window must fall within watch capture")

    hrv, analyzer_sha = _load_hrv()
    quality = hrv.analyze_session(payload)
    accepted = [item for item in quality["cleaned_intervals"] if item.get("accepted") is True]
    selected = [item for item in accepted if start <= ts + float(item["offset_ms"]) / 1000.0 <= end]
    runs: list[list[dict[str, Any]]] = []
    run: list[dict[str, Any]] = []
    for item in selected:
        if run:
            index_gap = int(item["index"]) != int(run[-1]["index"]) + 1
            offset_gap = float(item["offset_ms"]) - float(run[-1]["offset_ms"]) > hrv.TACHOGRAM_MAX_GAP_MS
            if index_gap or offset_gap:
                runs.append(run)
                run = []
        run.append(item)
    if run:
        runs.append(run)
    longest = max(runs, key=len, default=[])
    cadence = quality.get("sample_period_ms")
    if not _finite(cadence) and len(longest) >= 2:
        cadence = (float(longest[-1]["offset_ms"]) - float(longest[0]["offset_ms"])) / (len(longest) - 1)
    candidate = None
    coverage = 0.0
    # The respiration estimator assumes the backend's accepted uniform
    # tachogram.  Never manufacture a cadence for irregular beat streams.
    cadence_allowed = (quality.get("stream") == "tachogram_1hz" and
                       quality.get("cadence_consistent") is True and
                       all(float(b) >= float(a) for a, b in zip(offsets, offsets[1:])))
    if longest and _finite(cadence) and cadence_allowed:
        selected_start = ts + float(longest[0]["offset_ms"]) / 1000.0
        selected_end = ts + float(longest[-1]["offset_ms"]) / 1000.0
        coverage = max(0.0, selected_end - selected_start) / (end - start)
        if len(longest) >= hrv.RESP_MIN_SAMPLES and selected_end - selected_start >= hrv.MIN_SPAN_MS / 1000.0:
            candidate = hrv._respiration([float(item["ppi_ms"]) for item in longest], float(cadence), "manual")
    observed_bpm = float(count) * 60.0 / (end - start)
    comparison = None
    comparison_status = "insufficient_selected_run"
    if candidate and coverage >= 0.90:
        comparison = round(float(candidate["breaths_per_min"]) - observed_bpm, 3)
        comparison_status = "diagnostic_comparison"
    return {
        "format_version": 1,
        "qualified": False,
        "reliable": False,
        "calibration_enabled": False,
        "inputs": {"watch_sha256": watch_sha, "annotation_sha256": annotation_sha,
                    "watch_ts": watch["ts"], "annotation_capture": capture},
        "analyzer": {"name": "backend/hrv.py", "sha256": analyzer_sha,
                      "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        "observed": {"breath_count": count, "window": [start, end], "breaths_per_min": round(observed_bpm, 3)},
        "candidate": candidate,
        "selected_run": {"samples": len(longest), "coverage_fraction": round(coverage, 6)},
        "difference_breaths_per_min": comparison,
        "comparison_status": comparison_status,
        "motion": quality.get("motion"),
        "watch_diagnostic": {"status": quality.get("status"), "reasons": quality.get("reasons"),
                             "stream": quality.get("stream"), "sample_period_ms": quality.get("sample_period_ms")},
        "notes": ["Diagnostic candidate only; reliable and qualified are always false.",
                  "Watch onset timestamps are receipt-time estimates and carry transport uncertainty.",
                  "This breathing comparison is independent of stress and does not validate overnight breathing."],
    }


def _write_exclusive(path: Path, report: dict[str, Any]) -> None:
    data = (json.dumps(report, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("watch", type=Path)
    parser.add_argument("annotation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = analyze_breathing(args.watch, args.annotation)
    _write_exclusive(args.output, report)
    print(json.dumps({"output": str(args.output), "qualified": False}))


if __name__ == "__main__":
    main()
