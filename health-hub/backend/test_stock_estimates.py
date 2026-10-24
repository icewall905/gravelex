import unittest
from datetime import datetime, timezone

import stock_estimates


NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc).timestamp()


def row(days_ago, pulse=60, *, firmware="fw-a", collector="c1", **extra):
    ts = NOW - days_ago * 86400
    payload = {"context": "scheduled", "reported_hr": pulse, "hr_valid": 100,
               "duration_s": 600, "firmware": firmware, "collector_version": collector}
    payload.update(extra)
    return {"ts": ts, "payload": payload}


class StockEstimateTests(unittest.TestCase):
    def test_requires_three_distinct_earlier_nights_and_ignores_future(self):
        result = stock_estimates.build([row(0), row(1), row(2), row(3), row(-1)], [], {"score": 80}, None, NOW)
        self.assertEqual(result["pulse"]["status"], "ready")
        self.assertEqual(result["pulse"]["baseline_days"], 3)
        self.assertEqual(result["rejected"]["future_or_invalid_timestamp"], 1)

    def test_versions_are_not_pooled_and_unknown_zero_is_rejected(self):
        rows = [row(0, 60, firmware="new"), row(1, 61, firmware="old"),
                row(2, 61, firmware="old"), row(3, 61, firmware="old"), row(4, 0)]
        result = stock_estimates.build(rows, [], {"score": 80}, None, NOW)
        self.assertEqual(result["pulse"]["baseline_days"], 0)
        self.assertIn("pulse_invalid", result["rejected"])

    def test_integrity_and_vibration_are_excluded(self):
        rows = [row(0), row(1, hr_valid=10), row(2, vibration_samples=4), row(3)]
        result = stock_estimates.build(rows, [], {"score": 80}, None, NOW)
        self.assertEqual(result["pulse"]["baseline_days"], 1)
        self.assertIn("hr_valid_insufficient", result["rejected"])
        self.assertIn("vibration_samples_present", result["rejected"])

    def test_readiness_needs_two_components_and_ppi_never_enters_score(self):
        rows = [row(0, 60, ppi=[1, 2]), row(1), row(2), row(3)]
        result = stock_estimates.build(rows, [], {"score": 80}, None, NOW)
        self.assertEqual(result["readiness"]["status"], "estimated")
        self.assertFalse(result["readiness"]["components"].get("variability"))
        self.assertFalse(result["readiness"]["components"]["resting_hr"]["estimated"] is False)
        self.assertFalse(result["variability"]["used_for_readiness"])

    def test_stale_strain_and_missing_sleep_preserve_nulls(self):
        rows = [row(4), row(5), row(6), row(7)]
        result = stock_estimates.build(rows, [], {}, None, NOW)
        self.assertIsNone(result["strain"]["score"])
        self.assertIsNone(result["readiness"]["score"])
        self.assertIn("sleep:", " ".join(result["readiness"]["missing"]))

    def test_latest_is_object_and_higher_pulse_reduces_readiness_pulse(self):
        low = stock_estimates.build([row(0, 60), row(1, 60), row(2, 60), row(3, 60)], [], {"score": 80}, None, NOW)
        high = stock_estimates.build([row(0, 80), row(1, 60), row(2, 60), row(3, 60)], [], {"score": 80}, None, NOW)
        self.assertIsInstance(low["pulse"]["latest"], dict)
        self.assertIn("observed_at", low["pulse"]["latest"])
        self.assertGreater(low["readiness"]["components"]["resting_hr"]["score"],
                           high["readiness"]["components"]["resting_hr"]["score"])

    def test_previous_night_can_expire_strain_but_cannot_supply_readiness_pulse(self):
        result = stock_estimates.build([row(1), row(2), row(3), row(4)], [], {"score": 80}, None, NOW)
        self.assertIsNotNone(result["strain"]["score"])
        self.assertNotIn("resting_hr", result["readiness"]["components"])

    def test_bool_nan_and_bad_counter_integrity_are_rejected(self):
        bad = [row(0, float("nan")), row(1, 60, hr_valid=True), row(2, 60, hr_events=10), row(3)]
        result = stock_estimates.build(bad, [], {"score": 80}, None, NOW)
        self.assertEqual(result["pulse"]["baseline_days"], 0)
        self.assertIn("pulse_invalid", result["rejected"])
        self.assertIn("hr_valid_insufficient", result["rejected"])
        self.assertIn("hr_events_insufficient", result["rejected"])

    def test_supported_collector_contract_pools_only_validated_means(self):
        rows = []
        for days, collector, mean in ((0, "153", 60), (1, "152", 61), (2, "151", 62), (3, "150", 63)):
            item = row(days, firmware="same", collector=collector, mean_reported_hr=mean,
                       hr_sum=mean * 100, hr_valid=100)
            item["payload"].pop("reported_hr")
            rows.append(item)
        result = stock_estimates.build(rows, [], {"score": 80}, None, NOW)
        self.assertEqual(result["pulse"]["baseline_days"], 3)
        self.assertEqual(result["pulse"]["method_identity"]["collector_version"], "collector_contract150_153")
        self.assertEqual(result["pulse"]["points"][0]["collector_versions"], ["150"])

    def test_unknown_collector_and_firmware_do_not_pool(self):
        rows = [row(0, firmware="fw-new", collector="154"), row(1, firmware="fw-old", collector="153"),
                row(2, firmware="fw-old", collector="152"), row(3, firmware="fw-old", collector="151")]
        result = stock_estimates.build(rows, [], {"score": 80}, None, NOW)
        self.assertEqual(result["pulse"]["baseline_days"], 0)


    def test_unknown_firmware_does_not_qualify_even_after_many_nights(self):
        rows = [row(i, firmware="unknown") for i in range(6)]
        out = stock_estimates.build(rows, [], {"score": 80}, None, NOW)
        self.assertIsNotNone(out["pulse"]["latest"])
        self.assertEqual(out["pulse"]["baseline_days"], 0)
        self.assertIsNone(out["strain"]["score"])
        self.assertIsNone(out["readiness"]["score"])

    def test_oversized_numbers_and_boolean_training_are_rejected(self):
        out = stock_estimates.build([row(0, 10**10000)], [], {"score": 80},
            {"status": "ready", "date": "2026-10-24", "chronic": True, "acute": False}, NOW)
        self.assertIsNone(out["pulse"]["latest"])
        self.assertIsNone(out["readiness"]["score"])
        self.assertEqual(out["readiness"]["sleep_based_score"], 80)


    def test_ppi_changes_cannot_change_stock_scores_and_identity_survives_history(self):
        import sqlite3
        import readiness_history
        rows = [row(i, ppi=[900, 1000], offsets_ms=[30000, 31000]) for i in range(4)]
        a = stock_estimates.build(rows, [], {"score": 80}, None, NOW)
        for item in rows:
            item["payload"]["ppi"] = [10, 9999, 200]
            item["payload"]["offsets_ms"] = [0, 0, 999999]
        b = stock_estimates.build(rows, [], {"score": 80}, None, NOW)
        self.assertEqual(a["readiness"]["score"], b["readiness"]["score"])
        self.assertEqual(a["strain"]["score"], b["strain"]["score"])
        db = sqlite3.connect(":memory:")
        readiness_history.persist_daily(db, "2026-10-24", b["readiness"], NOW)
        stored = readiness_history.read_history(db, NOW-1, NOW+1)[0]["readiness"]
        self.assertEqual(stored["formula_version"], "readiness-stock-v1")
        self.assertEqual(stored["confidence"], "low_stock_proxy")
        self.assertEqual(stored["method_identity"]["comparable_series"]["firmware"], "fw-a")


if __name__ == "__main__":
    unittest.main()
