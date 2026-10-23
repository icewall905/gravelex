"""Focused tests for the private PPI delivery audit."""
from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from audit_ppi_delivery import audit_file, _least_squares_period


class AuditPpiDeliveryTest(unittest.TestCase):
    def write_capture(self, payload: dict) -> Path:
        directory = Path(tempfile.mkdtemp())
        path = directory / "synthetic-watch.json"
        path.write_text(json.dumps({"ts": 1, "payload": payload}))
        return path

    def test_duplicate_offsets_preserve_identical_and_different_values(self) -> None:
        row = audit_file(self.write_capture({
            "ppi": [1000, 1000, 1010, 1020],
            "offsets_ms": [0, 0, 1000, 1000],
            "duration_ms": 1000,
        }))
        self.assertEqual(row["duplicate_offset_count"], 2)
        self.assertEqual(row["duplicate_same_value_count"], 1)
        self.assertEqual(row["duplicate_different_value_count"], 1)

    def test_index_period_is_distorted_by_batches(self) -> None:
        offsets = [0, 1000, 1000, 2000]
        self.assertEqual(round(_least_squares_period(offsets), 3), 600.0)
        row = audit_file(self.write_capture({
            "ppi": [1000] * len(offsets), "offsets_ms": offsets, "duration_ms": 2000,
        }))
        self.assertEqual(row["positive_gap_median_ms"], 1000)
        self.assertEqual(row["least_squares_sample_period_ms"], 600.0)

    def test_interval_sum_is_only_a_ratio_not_beat_proof(self) -> None:
        row = audit_file(self.write_capture({
            "ppi": [900, 1100], "offsets_ms": [0, 2000], "duration_ms": 2000,
            "hr_events": 2, "hr_valid": 2, "hr_sum": 120,
        }))
        self.assertEqual(row["raw_ppi_sum_over_duration"], 1.0)
        self.assertEqual(row["reported_hr_based_beat_estimate"], 2.0)
        self.assertEqual(row["event_to_hr_beat_estimate_ratio"], 1.0)
        # Equal counters do not become a continuity assertion in the audit API.
        self.assertNotIn("beat_continuity", row)

    def test_invalid_nan_and_length_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            audit_file(self.write_capture({"ppi": [math.nan], "offsets_ms": [0]}))
        with self.assertRaises(ValueError):
            audit_file(self.write_capture({"ppi": [1000, 1000], "offsets_ms": [0]}))

    def test_report_output_is_exclusive_private_file(self) -> None:
        directory = Path(tempfile.mkdtemp())
        output = directory / "report.json"
        data_dir = Path(__file__).resolve().parents[1] / "reference-data"
        script = Path(__file__).resolve().parent / "audit_ppi_delivery.py"
        raw = data_dir / "motion153-frozen-quiet-20261023-watch.json"
        raw_before = raw.read_bytes()
        subprocess.run(["python3", str(script), str(data_dir), str(output)], check=True)
        before = output.read_bytes()
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        subprocess_result = subprocess.run(["python3", str(script), str(data_dir), str(output)], capture_output=True)
        self.assertNotEqual(subprocess_result.returncode, 0)
        self.assertEqual(output.read_bytes(), before)
        self.assertEqual(raw.read_bytes(), raw_before)

    def test_metadata_does_not_claim_physiological_one_hz(self) -> None:
        from audit_ppi_delivery import make_report
        directory = Path(__file__).resolve().parents[1] / "reference-data"
        findings = make_report(directory)["findings"]
        self.assertEqual(findings["one_hz_status"], "not established as a physiological sample clock")
        self.assertNotIn("supported as a delivery-clock observation", findings.get("one_hz_assumption", ""))


if __name__ == "__main__":
    unittest.main()
