from datetime import date, datetime
from zoneinfo import ZoneInfo

import briefing
import insights

CPH = ZoneInfo("Europe/Copenhagen")


def test_report_keeps_open_days_incomplete_fields_and_mixed_hrv_out():
    def daily_row(day, step_minutes):
        return {"date": day, "minutes": 1500, "hr_minutes": 200, "step_minutes": step_minutes,
                "steps": 0, "active_observed_minutes": 60, "active_minutes": 10,
                "overnight_hr_minutes": 60, "resting_hr": 55}

    report = insights.build({
        "now": int(datetime(2026, 10, 27, 12, tzinfo=CPH).timestamp()),
        "daily": [daily_row("2026-10-25", 1100), daily_row("2026-10-26", 1100),
                  daily_row("2026-10-27", 1440)],
        "history": [{"date": "2026-10-25", "complete": True, "load": 0},
                    {"date": "2026-10-26", "complete": False, "load": 40}],
        "recovery": {
            "sleep_nights": [{"night": "2026-10-25", "source": "sessions", "sleep_s": 25200},
                             {"night": "2026-10-26", "source": "estimated_minutes", "sleep_s": 25000}],
            "hrv_status": {"comparable_series": {"source": "current"}},
            "nights": [{"night": "2026-10-25", "comparable_series": {"source": "other"}, "rmssd_ms": 89},
                       {"night": "2026-10-26", "comparable_series": {"source": "current"}, "rmssd_ms": 42}],
        },
        "fitness": {"intensity": {"goal": 150, "this_week": 41}},
    }, CPH)
    long_day, last_day = report["days"][-2:]
    assert long_day["expected_minutes"] == 1500 and "steps" not in long_day
    assert long_day["confirmed_load"] == 0 and "confirmed_load" not in last_day
    assert long_day["sleep_minutes"] == 420 and "sleep_minutes" not in last_day
    assert "rmssd_ms" not in long_day and last_day["rmssd_ms"] == 42
    assert last_day["steps"] == 0 and "active_minutes" not in last_day
    assert report["through"] == "2026-10-26" and len(report["days"]) == 41
    assert report["metrics"]["steps"]["recent_median"] is None
    assert report["weekly_intensity_goal"]["even_split_minutes"] == 19


def test_rank_associations_respect_ties_lag_and_temporal_replication():
    assert insights.spearman([(0, i) for i in range(10)]) is None
    assert insights.ranks([2, 1, 2, 3]) == [1.5, 0, 1.5, 3]
    values = [i % 5 for i in range(40)]
    rows = [{"steps": x, "sleep_minutes": values[i-1] if i else 0}
            for i, x in enumerate(values)]
    link = insights.associations(rows)[0]
    assert link["status"] == "exploratory_pattern"
    assert (link["pairs"], link["lag_days"], link["rank_correlation"]) == (38, 1, 1)
    for row in rows[20:]:
        row["sleep_minutes"] *= -1
    assert insights.associations(rows)[0]["status"] == "no_consistent_pattern"
    assert insights.associations([{}] + rows[-10:])[0]["status"] == "insufficient_pairs"


def test_forecast_compares_prior_only_and_requires_predictive_skill():
    today = date(2026, 11, 20)
    variable = [{"steps": [2000, 8000, 9000, 6000][i % 4]} for i in range(41)]
    report = insights.step_forecast(variable, today)
    assert report["status"] == "available"
    assert report["model_mae"] < report["persistence_mae"]
    assert report["evaluation_days"] == 31 and report["date"] == today.isoformat()
    linear = [{"steps": 1000 + 100 * i} for i in range(41)]
    assert insights.step_forecast(linear, today)["status"] == "no_skill_over_persistence"
    assert insights.step_forecast(variable[:14], today)["estimate"] is None
    assert insights.step_forecast(variable[:-3] + [{}, {}, {}], today)["status"] == "insufficient_recent_data"


def test_briefing_keeps_only_an_available_patterns_action(monkeypatch):
    summary = {"now": 1795000000, "insights": {"suggested_actions": ["review_step_coverage"]}}
    reply = {"headline": "Coverage limited the comparison", "focus": "review_step_coverage"}
    def chat(messages, schema):
        if schema == briefing.PATTERNS_SCHEMA:
            assert "review_step_coverage" in messages[-1]["content"]
            return reply.copy(), "test"
        assert "review_step_coverage" not in messages[-1]["content"]
        return {"today": {"headline": "Today at a glance"}}, "test"

    monkeypatch.setattr(briefing, "_chat", chat)
    result = briefing.generate(summary, CPH)
    assert result["pages"]["patterns"]["focus"] == briefing.PATTERN_ACTIONS["review_step_coverage"]
    reply["focus"] = "review_training_days"
    assert briefing.generate(summary, CPH)["pages"]["patterns"]["focus"] == ""


def test_longer_history_preserves_old_evidence_without_filling_recording_gaps():
    from datetime import timedelta

    end = date(2026, 11, 19)
    days = []
    for i in range(56):
        stamp = end - timedelta(days=55-i)
        week_index = i // 7
        row = {"date": stamp.isoformat(), "expected_minutes": 1440}
        if week_index != 1:
            row.update(recorded_minutes=1200, steps=7000 if week_index in (0, 7) else 10000,
                       sleep_minutes=420 if week_index in (0, 7) else 500)
        days.append(row)
    history = insights.longer_history(days)
    assert len(history["observed_weeks"]) == 7
    assert len(history["older_observed_days"]) == 8
    assert history["comparable_past_weeks"] == [{
        "from": days[0]["date"], "through": days[6]["date"],
        "historical_minus_recent": {"steps": 0, "sleep_minutes": 0},
    }]
    assert insights.longer_history(days + [{"date": (end + timedelta(days=1)).isoformat()}])["through"] > end.isoformat()


def test_model_retries_transient_gateway_failure(monkeypatch):
    from io import StringIO
    from urllib.error import HTTPError

    monkeypatch.setenv("LLM_BASE_URL", "http://model.local/v1")
    monkeypatch.setattr(briefing.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(briefing, "_resolve", lambda base, headers, name: name)
    attempts = []

    def open_model(request, timeout):
        attempts.append(request)
        if len(attempts) == 1:
            raise HTTPError(request.full_url, 502, "gateway", {}, None)
        return StringIO('{"choices":[{"message":{"content":"{}"}}],"model":"local"}')

    monkeypatch.setattr(briefing, "model_settings", briefing._defaults)
    monkeypatch.setattr(briefing, "build_opener", lambda *_: type("Opener", (), {"open": staticmethod(open_model)})())
    assert briefing._chat([], briefing.PATTERNS_SCHEMA) == ({}, "local")
    assert len(attempts) == 2


def test_patterns_can_be_saved_when_standard_request_fails(monkeypatch):
    summary = {"now": 1795000000, "insights": {"suggested_actions": ["review_step_coverage"]}}

    def chat(messages, schema):
        if schema == briefing.SCHEMA:
            raise TimeoutError("temporary failure")
        return {"patterns": {"headline": "Coverage limited the comparison", "focus": "review_step_coverage"}}, "local"

    monkeypatch.setattr(briefing, "_chat", chat)
    result = briefing.generate(summary, CPH)
    assert list(result["pages"]) == ["patterns"]
    assert result["grounding"]["standard_status"] == "error"
    assert result["grounding"]["patterns_status"] == "ok"
