import json
import os
import stat
import sys
from pathlib import Path

import analyze_pair


def _fixture(tmp_path, *, raw_start=1000.0, watch_start=1000.0, duplicate=False, early=False):
    raw = tmp_path / "reference.jsonl"
    rows = [{"type": "session", "format_version": 1, "started_at": raw_start}]
    packet = {"type": "measurement", "sequence": 1, "received_at": raw_start,
              "packet_hex": "103c0004", "rr_ms": [1000.0]}
    rows.append(packet)
    rows.append({**packet, "sequence": 2, "received_at": raw_start + (0.01 if duplicate else 1.0)})
    rows.append({"type": "measurement", "sequence": 3, "received_at": raw_start + 2.0,
                 "packet_hex": "103d0004", "rr_ms": [1000.0]})
    rows.append({"type": "summary", "recording_completed": not early})
    raw.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    watch = tmp_path / "watch.json"
    payload = {"ppi": [1000] * 70, "offsets_ms": [i * 1000 for i in range(70)],
               "motion_total": 0, "motion_samples": 0, "stream_semantics": "latest_ppi_updates"}
    watch.write_text(json.dumps({"ts": watch_start, "payload": payload}))
    return raw, watch


def test_duplicate_duration_is_reported_and_never_deduped(tmp_path):
    raw, watch = _fixture(tmp_path, duplicate=True)
    report = analyze_pair.analyze_pair(raw, watch)
    assert report["qualified"] is False
    assert report["reference"]["rr_interval_count"] == 3
    assert "duplicate_rapid_identical_packets" in report["flags"]
    assert "rr_sum_exceeds_receipt_duration" in report["flags"]


def test_nonoverlap_is_rejected(tmp_path):
    raw, watch = _fixture(tmp_path, raw_start=1000.0, watch_start=2000.0)
    report = analyze_pair.analyze_pair(raw, watch)
    assert "nonoverlap" in report["flags"]
    assert report["overlap"]["observed_receipt_overlap_seconds"] == 0.0


def test_early_disconnect_and_segmented_rmssd(tmp_path):
    raw, watch = _fixture(tmp_path, early=True)
    report = analyze_pair.analyze_pair(raw, watch)
    assert "earlydisconnect" in report["flags"]
    assert report["reference"]["diagnostic"]["adjacent_pairs"] == 2
    json.dumps(report, allow_nan=False)


def test_cli_output_is_private_and_finite(tmp_path, monkeypatch):
    raw, watch = _fixture(tmp_path)
    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["analyze_pair", str(raw), str(watch), "--output", str(output)])
    analyze_pair.main()
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    json.loads(output.read_text())


def test_contact_false_and_parse_error_split_diagnostic_segments(tmp_path):
    raw, watch = _fixture(tmp_path)
    rows = [json.loads(line) for line in raw.read_text().splitlines()]
    rows[1]["contact_detected"] = False
    rows.insert(2, {"type": "parse_error", "sequence": 9, "received_at": 1000.5,
                    "error": "truncated", "packet_hex": "10"})
    raw.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    report = analyze_pair.analyze_pair(raw, watch)
    assert report["reference"]["rr_interval_count"] == 3
    assert report["reference"]["contact_false_packet_count"] == 1
    assert report["reference"]["diagnostic"]["count"] == 2
    assert "contact_false_packets" in report["flags"]


def test_paired_window_trims_reference_and_preserves_teardown_error(tmp_path):
    raw, watch = _fixture(tmp_path, raw_start=1000.0, watch_start=1001.0, early=True)
    rows = [json.loads(line) for line in raw.read_text().splitlines()]
    rows[-1].update(error="stop failed", error_stage="stop_notify")
    raw.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    report = analyze_pair.analyze_pair(raw, watch)
    assert report["paired_window_reference"]["receipt_timestamp_count"] < report["reference"]["receipt_timestamp_count"]
    assert report["reference"]["error"] == "stop failed"
    assert report["reference"]["error_stage"] == "stop_notify"


def test_missing_summary_and_missing_hr_do_not_invent_delta(tmp_path):
    raw, watch = _fixture(tmp_path)
    rows = [json.loads(line) for line in raw.read_text().splitlines()[:-1]]
    raw.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    payload = json.loads(watch.read_text())
    payload["payload"]["mean_reported_hr"] = 60
    watch.write_text(json.dumps(payload))
    report = analyze_pair.analyze_pair(raw, watch)
    assert "summary_missing_or_incomplete" in report["flags"]
    assert report["reference"]["watch_vs_reference_mean_delta_bpm"] is None


def test_fully_containing_fractional_window_has_no_partial_flag(tmp_path):
    raw, watch = _fixture(tmp_path, raw_start=1000.123, watch_start=1000.123)
    payload = json.loads(watch.read_text())
    payload["payload"]["offsets_ms"] = [0, 1900]
    payload["payload"]["ppi"] = [1000, 1000]
    watch.write_text(json.dumps(payload))
    report = analyze_pair.analyze_pair(raw, watch)
    assert "partial_watch_coverage" not in report["flags"]


def test_negative_watch_offset_rejected(tmp_path):
    raw, watch = _fixture(tmp_path)
    payload = json.loads(watch.read_text())
    payload["payload"]["offsets_ms"][0] = -1
    watch.write_text(json.dumps(payload))
    import pytest
    with pytest.raises(ValueError, match="offsets_ms"):
        analyze_pair.analyze_pair(raw, watch)
