import json
import hashlib
import os
import stat
from pathlib import Path

import pytest

import annotate_session


def _watch(tmp_path: Path, *, seconds: int = 120) -> Path:
    path = tmp_path / "watch.json"
    path.write_text(json.dumps({"ts": 1000, "payload": {"ppi": [1000] * (seconds + 1), "offsets_ms": [i * 1000 for i in range(seconds + 1)]}}))
    return path


def test_labels_are_saved_private_and_never_qualify(tmp_path):
    source = _watch(tmp_path)
    output = tmp_path / "labels.json"
    value = annotate_session.annotate_session(source, condition="quiet-seated", phase="held-out",
                                               observed_breath_count=14, observed_start=1010,
                                               observed_end=1070, stress_before=3, stress_after=6,
                                               observer_notes="awake and conversational")
    annotate_session._write_exclusive(output, value)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    saved = json.loads(output.read_text())
    assert saved["observed_breath_count"] == 14
    assert saved["capture"]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert saved["capture"]["ts"] == 1000
    assert saved["created_at"].endswith("+00:00")
    assert saved["physiological_qualification"] == {"qualified": False, "hrv": False, "breathing": False, "stress": False}
    assert "ppi" not in saved
    assert "awake spot checks only" in saved["protocol_notes"][0]


@pytest.mark.parametrize("kwargs", [
    {"observed_start": 1000, "observed_end": 1059, "observed_breath_count": 14},
    {"observed_start": 990, "observed_end": 1060, "observed_breath_count": 14},
    {"observed_start": 1010},
    {"observed_end": 1070},
])
def test_invalid_breath_windows_rejected(tmp_path, kwargs):
    with pytest.raises(ValueError):
        annotate_session.annotate_session(_watch(tmp_path), condition="other", phase="tuning", **kwargs)


@pytest.mark.parametrize("kwargs", [
    {"stress_before": True}, {"stress_after": 4.0}, {"stress_before": 11},
    {"observed_breath_count": True, "observed_start": 1010, "observed_end": 1070},
    {"observed_breath_count": -1, "observed_start": 1010, "observed_end": 1070},
    {"observed_breath_count": 14.5, "observed_start": 1010, "observed_end": 1070},
    {"observed_start": float("nan"), "observed_end": 1070},
])
def test_invalid_types_and_nonfinite_numbers_rejected(tmp_path, kwargs):
    with pytest.raises(ValueError):
        annotate_session.annotate_session(_watch(tmp_path), condition="other", phase="tuning", **kwargs)


def test_output_is_exclusive(tmp_path):
    source = _watch(tmp_path)
    output = tmp_path / "labels.json"
    value = annotate_session.annotate_session(source, condition="notification", phase="tuning")
    annotate_session._write_exclusive(output, value)
    with pytest.raises(FileExistsError):
        annotate_session._write_exclusive(output, value)


def test_stress_is_separate_from_hrv_qualification(tmp_path):
    value = annotate_session.annotate_session(_watch(tmp_path), condition="natural-movement", phase="held-out",
                                               stress_before=0, stress_after=10)
    assert value["stress_before"] == 0 and value["stress_after"] == 10
    assert value["physiological_qualification"]["stress"] is False
    assert value["physiological_qualification"]["hrv"] is False


def test_negative_offsets_and_zero_span_capture_rejected(tmp_path):
    negative = tmp_path / "negative.json"
    negative.write_text(json.dumps({"ts": 1000, "payload": {"offsets_ms": [-1, 1000]}}))
    zero = tmp_path / "zero.json"
    zero.write_text(json.dumps({"ts": 1000, "payload": {"offsets_ms": [0, 0]}}))
    for path in (negative, zero):
        with pytest.raises(ValueError):
            annotate_session.annotate_session(path, condition="other", phase="tuning")
