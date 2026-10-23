#!/usr/bin/env python3
"""Save private, human supplied labels for one captured watch recording.

This is an offline annotation tool.  It reads a saved ``{ts, payload}``
recording and never changes the recording or qualifies any physiological
measure.  Labels describe what an observer saw, rather than establishing
stress or overnight breathing truth.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any


CONDITIONS = ("quiet-seated", "natural-movement", "notification", "other")
PHASES = ("tuning", "held-out")
PROTOCOL_NOTES = [
    "Counted awake breaths support awake spot checks only; they do not validate overnight breathing.",
    "Subjective stress labels are not clinical measurements.",
    "This annotation never qualifies HRV, breathing, stress, readiness, or any other physiological measure.",
]


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _load_capture(path: Path) -> tuple[dict[str, Any], tuple[float, float], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or not isinstance(value.get("payload"), dict):
        raise ValueError("watch file must contain {ts, payload}")
    ts = value.get("ts")
    offsets = value["payload"].get("offsets_ms")
    if (not _finite(ts) or not isinstance(offsets, list) or not offsets or
            not all(_finite(v) and float(v) >= 0 for v in offsets)):
        raise ValueError("watch file needs finite ts and offsets_ms")
    start = float(ts) + min(float(v) for v in offsets) / 1000.0
    end = float(ts) + max(float(v) for v in offsets) / 1000.0
    if end <= start:
        raise ValueError("watch capture window must span more than zero seconds")
    return value, (start, end), hashlib.sha256(raw).hexdigest()


def _optional_finite(value: Any, name: str) -> float | None:
    if value is None:
        return None
    if not _finite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _stress(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10:
        raise ValueError(f"{name} must be an integer from 0 to 10")
    return value


def annotate_session(
    input_path: Path | str,
    *,
    condition: str,
    phase: str,
    observed_breath_count: Any = None,
    observed_start: Any = None,
    observed_end: Any = None,
    stress_before: Any = None,
    stress_after: Any = None,
    observer_notes: str | None = None,
) -> dict[str, Any]:
    """Validate and return an annotation; no output is written by this function."""
    input_path = Path(input_path)
    capture, (capture_start, capture_end), capture_sha256 = _load_capture(input_path)
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of: {', '.join(CONDITIONS)}")
    if phase not in PHASES:
        raise ValueError(f"phase must be one of: {', '.join(PHASES)}")
    if observer_notes is not None and not isinstance(observer_notes, str):
        raise ValueError("observer_notes must be a string")

    if observed_breath_count is not None and (
            isinstance(observed_breath_count, bool) or
            not isinstance(observed_breath_count, int) or observed_breath_count < 0):
        raise ValueError("observed_breath_count must be a nonnegative integer")
    breath = observed_breath_count
    start = _optional_finite(observed_start, "observed_start")
    end = _optional_finite(observed_end, "observed_end")
    if (start is None) != (end is None):
        raise ValueError("observed_start and observed_end must be supplied together")
    if breath is not None and start is None:
        raise ValueError("observed breath count requires an observed start/end window")
    if start is not None:
        if end < start:
            raise ValueError("observed breathing window is reversed")
        if start < capture_start or end > capture_end:
            raise ValueError("observed breathing window must fall within watch capture")
        if end - start < 60.0:
            raise ValueError("observed breathing window must be at least 60 seconds")

    before = _stress(stress_before, "stress_before")
    after = _stress(stress_after, "stress_after")
    annotation: dict[str, Any] = {
        "format_version": 1,
        "source": "offline_observer_annotation",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "capture": {
            "input": str(input_path),
            "window": [capture_start, capture_end],
            "sha256": capture_sha256,
            "ts": capture.get("ts"),
            "source": capture.get("source", capture.get("payload", {}).get("source")),
        },
        "condition": condition,
        "phase": phase,
        "observed_breath_count": breath,
        "observed_breath_window": [start, end] if start is not None else None,
        "stress_before": before,
        "stress_after": after,
        "observer_notes": observer_notes,
        "physiological_qualification": {
            "qualified": False,
            "hrv": False,
            "breathing": False,
            "stress": False,
        },
        "protocol_notes": PROTOCOL_NOTES,
    }
    # Keep the captured input out of the label file: annotations must not copy
    # or rewrite private raw physiological payloads.
    return annotation


def _write_exclusive(path: Path, value: dict[str, Any]) -> None:
    data = (json.dumps(value, allow_nan=False, indent=2, sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="saved watch JSON containing {ts, payload}")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--condition", choices=CONDITIONS, required=True)
    parser.add_argument("--phase", choices=PHASES, required=True)
    parser.add_argument("--observed-breath-count", type=int)
    parser.add_argument("--observed-start", type=float)
    parser.add_argument("--observed-end", type=float)
    parser.add_argument("--stress-before", type=int)
    parser.add_argument("--stress-after", type=int)
    parser.add_argument("--observer-notes")
    args = parser.parse_args()
    annotation = annotate_session(
        args.input, condition=args.condition, phase=args.phase,
        observed_breath_count=args.observed_breath_count,
        observed_start=args.observed_start, observed_end=args.observed_end,
        stress_before=args.stress_before, stress_after=args.stress_after,
        observer_notes=args.observer_notes,
    )
    _write_exclusive(args.output, annotation)
    print(json.dumps({"output": str(args.output), "qualified": False}))


if __name__ == "__main__":
    main()
