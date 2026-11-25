import sqlite3
from datetime import UTC, datetime, timedelta

import pytest
import planner_context


def test_recent_messages_and_account_local_vector_recall():
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        planner_context.archive(db, [{"role":"user", "text":"My preferred gym has sandbags."}])
        old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        planner_context.append(db, [{"role":"user", "text":"An ordinary unrelated message"}] * 39, old)
        now = datetime.now(UTC).isoformat()
        planner_context.append(db, [{"role":"trainer", "text":"Your program is ready."}], now)
        data = planner_context.recall(db, "gym sandbags")
        assert len(data["last_40_messages"]) == 40
        assert sum(row["current"] for row in data["last_40_messages"]) == 1
        assert data["relevant_older_messages"][0]["text"] == "My preferred gym has sandbags."


def test_model_endpoint_allowlist(monkeypatch):
    monkeypatch.setenv("PH_TRAINER_ROUTER_BASE", "https://router.example/v1")
    settings = planner_context.model_settings({"base_url":"https://router.example/v1/", "model":"custom/id"})
    assert settings["base_url"] == "https://router.example/v1"
    with pytest.raises(ValueError):
        planner_context.model_settings({"base_url":"https://other.example/v1", "model":"custom/id"})
