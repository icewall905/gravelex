import base64
import json
import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask, make_response

import external_api


class Provider:
    def __init__(self):
        self.data = {
            "minutes": [{"ts": 100, "hr": 60, "payload": {"private": True}}, {"ts": 200, "hr": 61}],
            "workouts": [{"start": 150, "seconds": 20, "id": "w1", "kind": "walk"}],
        }

    def __call__(self):
        return {"now": 300, "timezone": "UTC", "stock_estimates": {"readiness": {"score": 70, "status": "estimated"},
                "pulse": {"status": "ready", "latest": {"pulse": 60, "observed_at": 200}},
                "strain": {"score": 40, "status": "ready", "measured_at": 200}},
                "recovery": {"sleep": {"score": 80, "sleep_s": 28800}}, "weight": {}, "oxygen": {}, "training": {}, "hrv": {}}

    def history(self, resource, start, end):
        return self.data.get(resource, [])

    def raw_hrv(self, ident):
        return {"id": ident, "ppi": [1000, 1010]} if ident == "s1" else None


class ExternalApiTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(external_api.factory(Provider()))
        self.client = self.app.test_client()
        self.auth = patch.object(external_api.api_tokens, "authorize", return_value=None)
        self.auth.start()
        self.addCleanup(self.auth.stop)

    def test_summary_shape_and_null_preservation(self):
        response = self.client.get("/api/v1/summary")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["api_version"], "1")
        self.assertEqual(body["metrics"]["overnight_pulse"]["value"], 60)
        self.assertIsNone(body["metrics"]["spo2"])

    def test_history_bounds_pagination_and_no_raw_metadata(self):
        response = self.client.get("/api/v1/minutes?start=50&end=250&limit=1")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(len(body["items"]), 1)
        self.assertNotIn("payload", body["items"][0])
        cursor = body["pagination"]["next_cursor"]
        response = self.client.get(f"/api/v1/minutes?start=50&end=250&limit=1&cursor={cursor}")
        self.assertEqual(response.get_json()["items"][0]["ts"], 200)

    def test_cursor_range_and_resource_are_validated(self):
        response = self.client.get("/api/v1/minutes?start=50&end=250&limit=1")
        cursor = response.get_json()["pagination"]["next_cursor"]
        self.assertEqual(self.client.get(f"/api/v1/workouts?start=50&end=250&cursor={cursor}").status_code, 400)
        self.assertEqual(self.client.get(f"/api/v1/minutes?start=51&end=250&cursor={cursor}").status_code, 400)

    def test_scope_denial_is_returned_and_raw_is_separate(self):
        with self.app.app_context():
            denied = make_response("denied", 403)
        with patch.object(external_api.api_tokens, "authorize", return_value=denied):
            self.assertEqual(self.client.get("/api/v1/summary").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/hrv-sessions/s1/raw").get_json()["raw"]["id"], "s1")
        self.assertEqual(self.client.get("/api/v1/hrv-sessions/missing/raw").status_code, 404)

    def test_real_sqlite_history_adapter_uses_whitelisted_rows(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE minutes(ts INTEGER, hr INTEGER, steps INTEGER, active INTEGER, payload TEXT);
            CREATE TABLE sleep_sessions(start INTEGER, seconds INTEGER, kind TEXT);
            CREATE TABLE oxygen_samples(ts INTEGER, percent REAL, quality INTEGER, source TEXT);
            CREATE TABLE weights(day TEXT, kg REAL, source TEXT);
            CREATE TABLE hrv_sessions(id TEXT, ts INTEGER, payload TEXT);
        """)
        db.execute("INSERT INTO minutes VALUES(100,60,4,1,'{\"secret\":1}')")
        db.execute("INSERT INTO sleep_sessions VALUES(100,28800,'sleep')")
        db.execute("INSERT INTO oxygen_samples VALUES(100,98,2,'watch')")
        db.execute("INSERT INTO weights VALUES('1970-01-01',70,'scale')")
        db.execute("INSERT INTO hrv_sessions VALUES('s1',100,'{\"count\":60,\"ppi\":[1000]}')")
        db.commit()
        class FitnessStub:
            TZ = __import__("datetime").timezone.utc
            @staticmethod
            def connect():
                class Ctx:
                    def __enter__(self): return db
                    def __exit__(self, *args): return False
                return Ctx()
        with patch.object(external_api, "fitness", FitnessStub):
            self.assertEqual(external_api._db_history("minutes", 0, 200)[0], {"ts": 100, "hr": 60, "steps": 4, "active": 1})
            self.assertEqual(external_api._db_history("weights", 0, 86400)[0]["kg"], 70)
            self.assertNotIn("ppi", external_api._db_history("hrv-sessions", 0, 200)[0])


if __name__ == "__main__":
    unittest.main()
