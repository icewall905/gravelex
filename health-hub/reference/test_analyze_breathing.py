import hashlib
import json
import stat
from pathlib import Path

import pytest

import analyze_breathing


def _fixture(tmp_path, *, gap=None, count=18):
    watch = tmp_path / "watch.json"
    ppi = [1000 + 100 * __import__('math').sin(2 * __import__('math').pi * 0.2 * i) for i in range(151)]
    offsets = [i * 1000 for i in range(151)]
    if gap is not None:
        offsets[gap] += 4000
    watch.write_text(json.dumps({"ts": 1000, "payload": {"ppi": ppi, "offsets_ms": offsets,
                                                               "motion_samples": 10, "motion_total": 0,
                                                               "stream_semantics": "latest_ppi_updates"}}))
    annotation = tmp_path / "labels.json"
    annotation.write_text(json.dumps({"capture": {"sha256": hashlib.sha256(watch.read_bytes()).hexdigest()},
                                      "observed_breath_count": count,
                                      "observed_breath_window": [1030, 1120]}))
    return watch, annotation


def test_known_sinusoid_is_diagnostic_only_and_private(tmp_path):
    watch, annotation = _fixture(tmp_path)
    report = analyze_breathing.analyze_breathing(watch, annotation)
    assert report["qualified"] is False and report["reliable"] is False
    assert report["candidate"]["breaths_per_min"] > 0
    assert report["difference_breaths_per_min"] is not None
    assert report["analyzer"]["script_sha256"] == hashlib.sha256(Path(analyze_breathing.__file__).read_bytes()).hexdigest()
    output = tmp_path / "report.json"
    analyze_breathing._write_exclusive(output, report)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_missing_count_rejected(tmp_path):
    watch, annotation = _fixture(tmp_path)
    value = json.loads(annotation.read_text()); del value["observed_breath_count"]; annotation.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        analyze_breathing.analyze_breathing(watch, annotation)


def test_hash_mismatch_rejected(tmp_path):
    watch, annotation = _fixture(tmp_path)
    value = json.loads(annotation.read_text()); value["capture"]["sha256"] = "0" * 64; annotation.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        analyze_breathing.analyze_breathing(watch, annotation)


def test_gapped_data_has_no_comparison(tmp_path):
    watch, annotation = _fixture(tmp_path, gap=80)
    report = analyze_breathing.analyze_breathing(watch, annotation)
    assert report["difference_breaths_per_min"] is None
    assert report["comparison_status"] == "insufficient_selected_run"


def test_annotation_window_cannot_bypass_current_watch_gating(tmp_path):
    watch, annotation = _fixture(tmp_path)
    payload = json.loads(watch.read_text()); payload["payload"]["ppi"] = [1000] * 151; watch.write_text(json.dumps(payload))
    value = json.loads(annotation.read_text()); value["capture"]["sha256"] = hashlib.sha256(watch.read_bytes()).hexdigest(); annotation.write_text(json.dumps(value))
    report = analyze_breathing.analyze_breathing(watch, annotation)
    assert report["candidate"] is None
    assert report["watch_diagnostic"]["status"] != "experimental"


def test_write_failure_propagates(tmp_path):
    report = {"finite": True}
    with pytest.raises(FileExistsError):
        analyze_breathing._write_exclusive(tmp_path, report)


def test_nonmonotonic_offsets_are_insufficient_for_spectral_comparison(tmp_path):
    watch, annotation = _fixture(tmp_path)
    payload = json.loads(watch.read_text())
    payload["payload"]["offsets_ms"][70], payload["payload"]["offsets_ms"][71] = 72000, 70000
    watch.write_text(json.dumps(payload))
    value = json.loads(annotation.read_text())
    value["capture"]["sha256"] = hashlib.sha256(watch.read_bytes()).hexdigest()
    annotation.write_text(json.dumps(value))
    report = analyze_breathing.analyze_breathing(watch, annotation)
    assert report["difference_breaths_per_min"] is None
    assert report["watch_diagnostic"]["status"] == "insufficient"
