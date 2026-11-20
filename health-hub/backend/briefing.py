"""Nightly AI briefing: a short plain-language overview of every dashboard page.

The language model never calculates.  ``facts()`` turns the dashboard summary
into compact per-page facts, already compared with the wearer's own history,
and the model only phrases them.  Every number in its answer is checked
against those facts; a briefing with invented numbers is retried once with
the offending values listed, and anything still ungrounded is dropped.

Configuration (environment):
  LLM_BASE_URL     OpenAI-compatible endpoint, e.g. http://llm.lan:8080/v1
  LLM_MODEL        model name or alias (default "currentmodel")
  LLM_API_KEY      optional bearer token
  BRIEFING_TIME    local time(s) for the daily run, comma separated (default
                   "05:00,05:40"). Later times in a day only run when new
                   watch data has arrived since the last briefing, e.g. the
                   05:15 history export with last night's sleep sessions.

Run ``python3 briefing.py --daemon`` as its own service, or ``--once``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta
from statistics import mean, median
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import fitness
import accounts
from contextvars import copy_context

log = logging.getLogger("pebble-health.briefing")
FACTS_VERSION = 9
STANDARD_PAGES = ("today", "sleep", "recovery", "training", "more")
_running = threading.Lock()
PATTERN_ACTIONS = {
    "check_sync": "Check whether the watch and phone have synced recently.",
    "review_step_coverage": "Look at collection coverage before comparing your step totals.",
    "review_training_days": "Review recent training days and confirm the ones you can account for.",
    "review_weekly_goal": "Review the recorded minutes and the remaining weekly goal balance.",
}


def configured() -> bool:
    return bool(os.environ.get("LLM_BASE_URL"))


# --------------------------------------------------------------------------
# Facts: every number the model may use, computed here
# --------------------------------------------------------------------------

def _r(x, nd=1):
    return None if x is None else round(float(x), nd)


def _hm(seconds):
    if seconds is None:
        return None
    m = int(round(seconds / 60))
    return f"{m // 60}h {m % 60:02d}m"


def _version(code):
    return f"{code // 100}.{(code // 10) % 10}.{code % 10}" if code else None


def _clock(ts, tz):
    return datetime.fromtimestamp(ts, tz).strftime("%H:%M") if ts else None


def _avg(values):
    values = [v for v in values if v is not None]
    return mean(values) if values else None


def facts(s: dict[str, Any], tz) -> dict[str, Any]:
    now = datetime.fromtimestamp(s["now"], tz)
    today = now.date()
    collection = s.get("collection_health") or {}
    receipt_age = (collection.get("transport") or {}).get("age_seconds")
    rc = s.get("recovery") or {}
    identity = (rc.get("hrv_status") or {}).get("comparable_series")
    nights = [n for n in rc.get("nights") or [] if identity and n.get("comparable_series") == identity
              and n["night"] <= today.isoformat()]
    sleep_nights = rc.get("sleep_nights") or []
    fit = s.get("fitness") or {}
    weight = s.get("weight") or {}
    oxygen = s.get("oxygen") or {}
    oxygen_latest = oxygen.get("latest") or {}
    oxygen_daily = oxygen.get("daily") or []
    status = (s.get("latest") or {}).get("status") or {}

    # Daily steps from minute records (excluding the hourly snapshots).
    steps_by_day: dict[str, int] = {}
    for o in s.get("observations") or []:
        if not o.get("snapshot") and o.get("steps"):
            d = datetime.fromtimestamp(o["ts"], tz).date().isoformat()
            steps_by_day[d] = steps_by_day.get(d, 0) + o["steps"]
    last7 = [(today - timedelta(days=i)).isoformat() for i in range(1, 8)]

    sleep_recent = [n for n in sleep_nights if today - timedelta(days=7) < date.fromisoformat(n["night"]) <= today]
    last_sleep = next((n for n in sleep_nights if n["night"] == today.isoformat()), None)
    hrv_recent = [n for n in nights if today - timedelta(days=7) < date.fromisoformat(n["night"]) <= today]
    last_hrv = next((n for n in nights if n["night"] == today.isoformat()), None)
    hs, sl, ready = rc.get("hrv_status") or {}, rc.get("sleep") or {}, rc.get("readiness") or {}

    report = s.get("insights") or {}
    if report and s.get("briefing_history"):
        report = dict(report, longer_history=s["briefing_history"])
    sleep_vs_hrv = next((link["rank_correlation"] for link in report.get("associations", [])
                         if link["predictor"] == "sleep_minutes" and link["outcome"] == "rmssd_ms"), None)

    collector = s.get("collector") or {}
    night_sessions_today = (last_hrv or {}).get("sessions", 0)
    it = fit.get("intensity") or {}
    vo2 = fit.get("vo2max") or {}
    t = (s.get("training") or {}).get("latest") or {}
    unconfirmed = [h["date"] for h in (s.get("history") or [])[-7:] if not h.get("complete")]

    def sleep_detail(n):
        def spans(key):
            return [{"start": datetime.fromtimestamp(a, tz).isoformat(),
                     "end": datetime.fromtimestamp(b, tz).isoformat(), "duration": _hm(b-a)}
                    for a, b in n.get(key, [])]
        return {"night": n["night"], "source": n.get("source"),
                "duration": _hm(n.get("sleep_s")), "restful_duration": _hm(n.get("restful_s")),
                "non_restful_duration": _hm(max(0, n["sleep_s"]-n["restful_s"]))
                    if n.get("restful_s") is not None else None,
                "sleep_onset": datetime.fromtimestamp(n["onset"], tz).isoformat() if n.get("onset") else None,
                "wake": datetime.fromtimestamp(n["wake"], tz).isoformat() if n.get("wake") else None,
                "sleep_intervals": spans("sleep_intervals"),
                "restful_intervals": spans("restful_intervals"),
                "recorded_gaps": spans("recorded_gaps"),
                "gap_count": len(n["recorded_gaps"]) if "recorded_gaps" in n else None,
                "gap_duration": _hm(sum(b-a for a,b in n["recorded_gaps"])) if "recorded_gaps" in n else None}

    recent_workouts = []
    for w in s.get("workouts") or []:
        start = w.get("start", 0)
        end = start + (w.get("seconds") or 0)
        if not s["now"] - 7*86400 <= start <= s["now"] or w.get("excluded"):
            continue
        onset = (last_sleep or {}).get("onset")
        recent_workouts.append({"start": datetime.fromtimestamp(start, tz).isoformat(),
            "end": datetime.fromtimestamp(end, tz).isoformat(), "kind": w.get("kind"),
            "duration": _hm(w.get("seconds")), "rpe": w.get("rpe"), "load": w.get("load"),
            "hours_before_last_sleep": _r((onset-end)/3600) if onset and end <= onset else None,
            "before_last_sleep": end <= onset if onset else None})

    return {
        "facts_version": FACTS_VERSION,
        "date": today.isoformat(), "weekday": now.strftime("%A"), "time": now.strftime("%H:%M"),
        "name": s.get("wearer") or None,
        "patterns": report or None,
        "today": {
            "oxygen": {"status": oxygen.get("status", "waiting_for_data"), "latest_percent": oxygen_latest.get("percent"), "raw_device_quality": oxygen_latest.get("quality"),
                       "measured_at": datetime.fromtimestamp(oxygen_latest["ts"], tz).isoformat() if oxygen_latest.get("ts") else None,
                       "sample_count_in_range": oxygen.get("sample_count", 0), "daily": oxygen_daily[-7:],
                       "limitation": "Experimental optical spot samples, not continuous oxygen or an apnea assessment; missing samples are unknown; not a readiness input."},
            "readiness_score": ready.get("score"), "readiness_status": ready.get("status"),
            "readiness_inputs": {k: v.get("score") for k, v in (ready.get("components") or {}).items()},
            "readiness_missing": ready.get("missing"),
            "readiness_method": ready.get("formula_version"),
            "readiness_estimated": ready.get("estimated", ready.get("provisional", True)),
            "readiness_confidence": ready.get("confidence"),
            "sleep_only_guidance_score": ready.get("sleep_based_score"),
            "steps_so_far_today": (s.get("current_activity") or {}).get("steps"),
            "activity_observation": s.get("current_activity"), "steps_daily_avg_previous_7_days": _r(_avg(steps_by_day.get(d) for d in last7), 0),
            "watch_battery_percent": (s.get("watch_battery") or {}).get("percent"),
            "watch_battery_observation": {k: v for k, v in (s.get("watch_battery") or {}).items() if k != "series"},
            "weight_latest_weigh_in_kg": (weight.get("latest") or {}).get("kg"),
            "weight_7_day_average_kg": (weight.get("latest") or {}).get("trend_kg"),
            "weight_7_day_average_change_over_last_week_kg": weight.get("change_7d_kg"),
            "weight_7_day_average_change_over_last_4_weeks_kg": weight.get("change_28d_kg"),
            "intensity_minutes_this_week": it.get("this_week"), "intensity_goal": it.get("goal"),
            "days_left_this_week": 6 - today.weekday(),
        },
        "sleep": {
            "last_night_duration": _hm(last_sleep["sleep_s"]) if last_sleep else None,
            "last_night_restful_duration": _hm(last_sleep.get("restful_s")) if last_sleep else None,
            "last_night_detail": sleep_detail(last_sleep) if last_sleep else None,
            "recent_workouts": recent_workouts,
            "limitations": "Onset is first recorded sleep, not bedtime or sleep latency. Non-restful sleep is not confirmed restlessness or wakefulness. Gaps may be wakefulness or missing recording. No sleep-stage measurement. Daily totals do not establish interval timing.",
            "last_night_bedtime": _clock((last_sleep or {}).get("onset"), tz),
            "last_night_wake": _clock((last_sleep or {}).get("wake"), tz),
            "sleep_score": sl.get("score"), "score_status": sl.get("status"), "need_hours": _r((sl.get("need_s") or 0) / 3600),
            "regularity_sd_minutes": sl.get("regularity_sd_min"),
            "average_duration_previous_nights": _hm(_avg(n["sleep_s"] for n in sleep_recent if n["night"] != today.isoformat())),
            "previous_nights_in_average": sum(1 for n in sleep_recent if n["night"] != today.isoformat()),
            "nights_recorded_last_7": len(sleep_recent),
            "sleep_debt_last_7_nights": _hm(sum(max(0, (sl.get("need_s") or 28800) - n["sleep_s"]) for n in sleep_recent)),
            "nights": [sleep_detail(n) for n in sleep_recent],
        },
        "recovery": {
            "hrv_last_night_ms": (last_hrv or {}).get("rmssd_ms"),
            "hrv_avg_previous_nights_ms": _r(_avg(n["rmssd_ms"] for n in hrv_recent if n["night"] != today.isoformat())),
            "hrv_previous_nights_in_avg": sum(1 for n in hrv_recent if n["night"] != today.isoformat()),
            "hrv_status": hs.get("status"), "hrv_status_provisional": hs.get("provisional"),
            "hrv_usual_range_ms": [hs.get("baseline_low_ms"), hs.get("baseline_high_ms")] if hs.get("baseline_low_ms") else None,
            "hrv_nights_recorded": hs.get("baseline_nights"), "hrv_nights_needed": hs.get("required_baseline_nights"),
            "pulse_during_night_recording_bpm": (last_hrv or {}).get("resting_hr"),
            "resting_pulse_night_minimum_bpm": fit.get("resting_hr"),
            "breathing_per_min": (last_hrv or {}).get("breaths_per_min"),
            "qualified_night_recordings_last_night": night_sessions_today, "night_recordings_planned": None,
            "stress_status": (s.get("stress") or {}).get("status"),
            "stock_firmware_estimates": {
                "mode": (s.get("stock_estimates") or {}).get("mode"),
                "overnight_pulse": (s.get("stock_estimates") or {}).get("pulse"),
                "overnight_strain": (s.get("stock_estimates") or {}).get("strain"),
                "limitation": "Custom low-confidence estimates from direct pulse summaries, sleep and available confirmed training; not validated vendor scores or psychological stress. Pulse variability and breathing are not inputs."},
            "monitor_diagnostics":(s.get("monitor_observations") or {}).get("diagnostics",{}),
            "overnight_spot_pulse":(s.get("monitor_observations") or {}).get("nightly_pulse",[])[-7:],
            "hrv_comparable_series": identity,
            "hrv_capture_quality": {k:(s.get("hrv",{}).get("quality") or {}).get(k) for k in
                                    ("status","source","algorithm_version","metric","stream",
                                     "delivery","reasons","motion")},
            # Delivered-PPI variation is intentionally kept out of briefing
            # facts: it is a transport diagnostic and must never be phrased as
            # HRV, readiness, stress, or breathing.
            "hrv_source_blocked_reason": (
                "beat continuity unverified; delivered PPI variation is diagnostic only"
                if ((s.get("hrv",{}).get("quality") or {}).get("stream") == "batched_ppi_unverified"
                    or (s.get("hrv",{}).get("quality") or {}).get("metric") == "delivered_ppi_variation_unverified"
                    or (s.get("hrv",{}).get("quality") or {}).get("status") == "beat_continuity_unverified")
                else None),
            "stress_observation": {k:(s.get("stress") or {}).get(k) for k in ("measured_at","age_seconds","expires_at","context","reason")},
            "nights": [{"night": n["night"], "hrv_ms": n["rmssd_ms"], "pulse_bpm": n["resting_hr"], "breathing": n["breaths_per_min"]} for n in hrv_recent],
            "link_sleep_hours_vs_hrv_rank_correlation": sleep_vs_hrv,
        },
        "training": {
            "vo2max_estimate": vo2.get("value"), "vo2max_method": vo2.get("method"), "bmi": (vo2.get("inputs") or {}).get("bmi"),
            "activity_rating_0_7": (vo2.get("inputs") or {}).get("pa_rating"),
            "intensity_minutes_last_7_days": it.get("last_7_days"), "intensity_minutes_this_week": it.get("this_week"),
            "intensity_goal_per_week": it.get("goal"),
            "load_acute": t.get("acute"), "load_chronic": t.get("chronic"), "load_status": t.get("status"),
            "workouts_last_7_days": sum(1 for w in s.get("workouts") or [] if w.get("start", 0) >= s["now"] - 7 * 86400),
            "unconfirmed_days_last_7": len(unconfirmed),
            "max_hr_setting": fit.get("hr_max"),
        },
        "more": {
            "hours_since_last_upload": _r(receipt_age / 3600, 1) if receipt_age is not None else None,
            "collection_evidence": {k:collection.get(k) for k in ("transport","measurements","daily","collector","watch_phone_transfer","phone_backlog")},
            "watch_battery_percent": (s.get("watch_battery") or {}).get("percent"),
            "watch_battery_observation": {k: v for k, v in (s.get("watch_battery") or {}).items() if k != "series"},
            "hrv_app_version": _version(collector.get("collector_version")),
            "night_slots_armed": collector.get("schedule_ok"),
            "next_night_recording": datetime.fromtimestamp(collector["next_wakeup"], tz).strftime("%a %H:%M") if collector.get("next_wakeup",0)>s["now"] else None,
            "qualified_night_recordings_last_night": night_sessions_today, "night_recordings_planned": None,
            "minute_records_total": s.get("minute_records"),
        },
    }


# --------------------------------------------------------------------------
# Prompt and grounding check
# --------------------------------------------------------------------------

SYSTEM = """You write the morning briefing for a personal health dashboard fed by a Pebble smartwatch.
Write for one person, in plain, warm, direct English, like a good coach: no hype, no filler.
Rules:
- Use ONLY the facts given. Every number you write must appear in the facts (you may round it). Never calculate new numbers.
- Missing (null) values mean "not measured yet": say so briefly when it matters, never guess.
- Scores here are experimental personal estimates, not medical measurements. Never diagnose or give medical advice.
- Stock-firmware readiness and overnight strain are custom low-confidence estimates. Call them estimated; overnight pulse is a sparse filtered spot summary, not proven resting HR. Overnight strain is not current daytime or psychological stress, and must retain its observation date. Sleep-only guidance is not overall readiness. Training load may be missing. Do not diagnose causes of a pulse change.
- Batched PPI delivery diagnostics are transport observations only. Never call them HRV/RMSSD, readiness, stress, breathing, or a cadence failure; report the source-blocked reason when present.
- SpO2 is experimental optical spot sampling. State its actual measurement date and sparse coverage when discussed. Do not infer sleep apnea, hypoxia duration, diagnosis, recovery benefit or normality from it. No samples means unknown, not zero.
- Prefer comparisons with the person's own history over absolute judgements.
- The "focus" is one practical, specific suggestion for today, grounded in the facts.
- Lead with what changed or matters most and why; do not list every number. Mention a missing value at most once per page.
- Say each point once: the headline, summary, highlights and focus must not repeat each other.
- An average built from fewer than 3 earlier values is not a baseline: call the value "the first reading" or similar instead of comparing.
- Interpret, do not just restate: e.g. a short night after a long one, a debt building up, a recording that failed and needs attention.
- Use tones honestly and decisively: "good" for better than usual or on track; "watch" for clearly worse than usual, a goal at risk or something to fix (e.g. 2+ hours of sleep debt, a missed night recording, a stale upload); "neutral" only for plain context.
- Write durations as given (e.g. "5h 41m"), never as decimal hours.
- Keep it short: headline <= 12 words, summary <= 2 sentences, 2-4 highlights of <= 20 words each.
Return JSON exactly matching the schema."""

PATTERNS_SYSTEM = SYSTEM + """
Write only the Patterns page. These instructions take priority for this page:
- In patterns, use the dated longitudinal evidence and the provided medians, deltas and coverage. Compare distinct time windows, and explain how missing days may affect the comparison. The activity forecast is conditional on adequately recorded days and describes recorded steps; its typical error comes from historical replay. The weekly goal balance is planning arithmetic, never a prescription or a reason to increase training today.
- Use longer_history to look for sustained changes or earlier periods with similar observations. Its weekly windows are disjoint and end at the most recent completed date. Use comparable_past_weeks as examples of similar observation profiles. They do not predict what happens next. Omitted dates and weeks have no usable measurements in this record. Describe the dated examples you actually use and their sample counts when helpful.
- Discuss only associations marked exploratory_pattern. State which metric preceded the other when lag_days is set. Give sample counts when helpful. These are exploratory rank associations, not effects or medical findings. Avoid any claim about unmeasured factors. Treat the two windows as checks of consistency, not independent studies.
- For the patterns focus field, return exactly one action code from suggested_actions, or an empty string. The dashboard translates the code to readable text.
"""

PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "highlights": {"type": "array", "items": {"type": "object", "properties": {
            "text": {"type": "string"}, "tone": {"type": "string", "enum": ["good", "neutral", "watch"]}},
            "required": ["text", "tone"]}},
        "focus": {"type": "string"},
        "data_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "summary", "highlights", "focus", "data_notes"],
}
SCHEMA = {"type": "object", "properties": {p: PAGE_SCHEMA for p in STANDARD_PAGES},
          "required": list(STANDARD_PAGES)}
PATTERNS_SCHEMA = {"type": "object", "properties": {"patterns": {
    **PAGE_SCHEMA, "properties": {**PAGE_SCHEMA["properties"],
                                 "focus": {"type": "string", "enum": ["", *PATTERN_ACTIONS]}}
}}, "required": ["patterns"]}

PAGE_GUIDE = {
    "today": "The big picture for the day: readiness, last night, activity so far, weight trend, intensity goal.",
    "sleep": "Analyze last night: onset, wake, duration, quieter/non-restful intervals and recorded gaps against recent nights, regularity and debt. Discuss recent workout timing, duration, effort and available load alongside recovery pulse, qualified HRV and activity context from other pages. Distinguish workouts before sleep from those afterward. Describe possible associations, never claim causation. Respect sleep limitations; do not invent awakenings, restlessness, stages or missing lifestyle factors. Give one practical suggestion grounded in the observations.",
    "recovery": "Overnight HRV, pulse and breathing against recent nights; baseline progress; any sleep/HRV link.",
    "training": "Intensity minutes against the weekly goal, training load status, VO2max estimate and what moves it.",
    "patterns": "Explain the most useful longer-term change, and an exploratory association or an honest limit on what can be inferred. Use dated evidence when useful. Prefer actionable data gaps over repeating the other pages.",
    "more": "Is the setup healthy: uploads, battery, night recordings arriving, anything the person should fix.",
}

_NUM = re.compile(r"(?<![\w.])[-−+]?\d+(?:[.,]\d+)?")


def _numbers(obj) -> list[float]:
    out = []
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return [float(m.replace("−", "-").replace(",", ".")) for m in _NUM.findall(obj)]
    if isinstance(obj, dict):
        for v in obj.values():
            out += _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _numbers(v)
    return out


def ungrounded(text: str, allowed: set[float]) -> list[str]:
    """Numbers in ``text`` that don't match a fact (allowing rounding)."""
    bad = []
    for m in _NUM.findall(text):
        v = abs(float(m.replace("−", "-").replace(",", ".")))
        if v <= 10 and float(v).is_integer():
            continue  # small counts and ordinals ("2 nights", "1 of 3") are fine
        tol = max(0.51, abs(v) * 0.02)
        if not any(abs(v - abs(a)) <= tol for a in allowed):
            bad.append(m)
    return bad


def _allowed(f: dict[str, Any]) -> set[float]:
    nums = set(_numbers(f))
    nums |= {round(n * 60) for n in list(nums) if 0 < n < 24}  # hours shown as minutes
    for t in re.findall(r"\b(\d{1,2}):(\d{2})\b", json.dumps(f)):
        nums |= {float(t[0]), float(t[1])}  # clock times
    return nums


def _chat(messages: list[dict[str, str]], schema) -> tuple[dict[str, Any], str]:
    base = os.environ["LLM_BASE_URL"].rstrip("/")
    body = {"model": os.environ.get("LLM_MODEL", "currentmodel"), "messages": messages, "temperature": 0.4,
            # Reasoning counts against the output budget, and the model is much
            # better with it on; this runs once a night, so be generous.
            "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "32000")), "response_format": {"type": "json_object", "schema": schema}}
    headers = {"Content-Type": "application/json"}
    if os.environ.get("LLM_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["LLM_API_KEY"]
    request = Request(base + "/chat/completions", json.dumps(body).encode(), headers)
    for delay in (0, 3, 10):
        if delay:
            time.sleep(delay)
        try:
            with urlopen(request, timeout=1800) as response:
                reply = json.load(response)
            break
        except HTTPError as error:
            if error.code not in (502, 503, 504) or delay == 10:
                raise
            log.warning("retrying briefing model after gateway HTTP %d", error.code)
            error.close()
    content = reply["choices"][0]["message"]["content"] or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    content = re.sub(r"^```(?:json)?|```$", "", content).strip()
    return json.loads(content), _resolve(base, headers, reply.get("model") or body["model"])


def _resolve(base: str, headers: dict[str, str], name: str) -> str:
    """Report the real model behind an alias such as "currentmodel"."""
    try:
        with urlopen(Request(base + "/models", headers=headers), timeout=10) as r:
            for m in json.load(r).get("data", []):
                if m.get("id") == name and m.get("alias_of"):
                    return m["alias_of"]
    except Exception:
        pass
    return name


class EmptyBriefing(ValueError):
    pass


def _normalise(result: dict[str, Any], pages) -> dict[str, Any]:
    """Servers don't always enforce the schema: unwrap one nesting level and
    accept plain-string highlights (taking a page-level tone if given)."""
    if isinstance(result, dict) and not any(p in result for p in pages):
        inner = [v for v in result.values() if isinstance(v, dict) and any(p in v for p in pages)]
        if inner:
            result = inner[0]
        elif len(pages) == 1 and ("headline" in result or "summary" in result):
            result = {pages[0]: result}
    if not isinstance(result, dict):
        result = {}
    normalised = {}
    for page in pages:
        p = result.get(page) if isinstance(result.get(page), dict) else {}
        page_tone = p.get("tone") if p.get("tone") in ("good", "neutral", "watch") else "neutral"
        p["highlights"] = [h if isinstance(h, dict) else {"text": str(h), "tone": page_tone} for h in p.get("highlights") or []]
        for h in p["highlights"]:
            if h.get("tone") not in ("good", "neutral", "watch"):
                h["tone"] = "neutral"
        p["data_notes"] = [str(n) for n in p.get("data_notes") or []]
        for key in ("headline", "summary", "focus"):
            p[key] = str(p.get(key) or "")
        normalised[page] = p
    if not any(normalised[p]["headline"] or normalised[p]["summary"] for p in pages):
        raise EmptyBriefing("model returned no usable page content")
    return normalised


def _check(result: dict[str, Any], allowed: set[float]) -> dict[str, list[str]]:
    problems = {}
    for page, p in result.items():
        texts = [p["headline"], p["summary"], p["focus"]] + [
            h.get("text", "") for h in p["highlights"]] + p["data_notes"]
        bad = sorted({b for t in texts for b in ungrounded(t, allowed)})
        if bad:
            problems[page] = bad
    return problems


def _scrub(result: dict[str, Any], allowed: set[float]) -> None:
    """Drop any remaining sentence-level item with an ungrounded number."""
    for p in result.values():
        p["highlights"] = [h for h in p["highlights"] if not ungrounded(h.get("text", ""), allowed)][:4]
        p["data_notes"] = [n for n in p["data_notes"] if not ungrounded(n, allowed)][:3]
        for key in ("headline", "summary", "focus"):
            if ungrounded(p[key], allowed):
                p[key] = ""


def _write(facts, guides, system, schema):
    pages = tuple(guides)
    allowed = _allowed(facts)
    shape = {p: {"headline": "...", "summary": "...", "highlights": [{"text": "...", "tone": "good|neutral|watch"}],
                 "focus": "...", "data_notes": ["..."]} for p in pages}
    user = ("Page guide:\n" + json.dumps(guides) +
            "\n\nFacts (null = not measured yet):\n" + json.dumps(facts, separators=(",", ":")) +
            "\n\nWrite the requested pages using exactly this JSON shape:\n" + json.dumps(shape))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    retried = False
    try:
        result, model = _chat(messages, schema)
        result = _normalise(result, pages)
    except (EmptyBriefing, json.JSONDecodeError):
        retried = True
        result, model = _chat(messages, schema)
        result = _normalise(result, pages)
    problems = _check(result, allowed)
    if problems:
        retried = True
        messages += [{"role": "assistant", "content": json.dumps(result)},
                     {"role": "user", "content": "These numbers do not appear in the facts: " + json.dumps(problems) +
                      ". Rewrite these pages using only numbers from the facts."}]
        result, model = _chat(messages, schema)
        result = _normalise(result, pages)
    remaining = _check(result, allowed)
    _scrub(result, allowed)
    return result, model, retried, remaining


def generate(summary: dict[str, Any], tz) -> dict[str, Any]:
    f = facts(summary, tz)
    standard_facts = {key: value for key, value in f.items() if key != "patterns"}
    standard_guides = {key: PAGE_GUIDE[key] for key in STANDARD_PAGES}
    try:
        pages, model, retried, remaining = _write(standard_facts, standard_guides, SYSTEM, SCHEMA)
        if not any(page["headline"] or page["summary"] for page in pages.values()):
            raise EmptyBriefing("standard pages failed the evidence checks")
        standard_status = "ok"
    except Exception:
        log.exception("standard briefing failed")
        pages, model, retried, remaining = {}, None, False, {}
        standard_status = "error"
    patterns_status = "no_data"
    if (report := f["patterns"]):
        try:
            response, patterns_model, patterns_retried, patterns_remaining = _write(
                report, {"patterns": PAGE_GUIDE["patterns"]}, PATTERNS_SYSTEM, PATTERNS_SCHEMA)
            retried = retried or patterns_retried
            remaining.update(patterns_remaining)
            patterns = response["patterns"]
            if not (patterns["headline"] or patterns["summary"]):
                raise EmptyBriefing("patterns page failed the evidence checks")
            selected = patterns["focus"]
            actions = report.get("suggested_actions", [])
            patterns["focus"] = PATTERN_ACTIONS.get(selected, "") if selected in actions else ""
            pages["patterns"] = patterns
            model = model or patterns_model
            patterns_status = "ok"
        except Exception:
            log.exception("patterns briefing failed")
            patterns_status = "error"
    if not pages:
        raise EmptyBriefing("neither briefing request produced usable pages")
    return {"pages": pages, "model": model, "facts": f,
            "grounding": {"retried": retried, "dropped_numbers": remaining,
                          "standard_status": standard_status, "patterns_status": patterns_status}}


# --------------------------------------------------------------------------
# Storage, run and schedule
# --------------------------------------------------------------------------

def latest(db) -> dict[str, Any] | None:
    row = db.execute("SELECT created,day,model,payload FROM briefings WHERE status='ok' ORDER BY created DESC LIMIT 1").fetchone()
    if not row:
        return None
    payload = json.loads(row["payload"])
    return {"created": row["created"], "day": row["day"], "model": row["model"], "pages": payload["pages"],
            "grounding": payload.get("grounding"),
            "requires_refresh": (payload.get("facts") or {}).get("facts_version") != FACTS_VERSION}


def run() -> str:
    """Generate and store one briefing; returns 'ok', 'busy', 'disabled' or 'error'."""
    if not configured():
        return "disabled"
    if not _running.acquire(blocking=False):
        return "busy"
    try:
        summary = fitness.summary(42)
        started = time.time()
        try:
            if summary.get("insights"):
                summary["briefing_history"] = fitness.briefing_history(summary)
            out = generate(summary, fitness.TZ)
            status, error = "ok", None
        except Exception as exc:
            log.exception("briefing failed")
            out, status, error = {"pages": None, "model": os.environ.get("LLM_MODEL"), "facts": None}, "error", str(exc)[:500]
        with fitness.connect() as db:
            db.execute("INSERT INTO briefings(created,day,model,status,payload,error,seconds) VALUES(?,?,?,?,?,?,?)",
                       (int(time.time()), datetime.now(fitness.TZ).date().isoformat(), out.get("model"), status,
                        json.dumps(out), error, round(time.time() - started, 1)))
        return status
    finally:
        _running.release()


def run_in_background() -> str:
    if not configured():
        return "disabled"
    if _running.locked():
        return "busy"
    context=copy_context()
    threading.Thread(target=lambda: context.run(run), daemon=True).start()
    return "started"


def _times() -> list[tuple[int, int]]:
    out = []
    for part in os.environ.get("BRIEFING_TIME", "05:00,05:40").split(","):
        hh, mm = part.strip().split(":")
        out.append((int(hh), int(mm)))
    return sorted(out)


def _next_run(now: datetime) -> tuple[datetime, bool]:
    """Next scheduled time, and whether it is the first of its day."""
    times = _times()
    for i, (hh, mm) in enumerate(times):
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target > now:
            return target, i == 0
    hh, mm = times[0]
    return now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=1), True


def new_data_since_last_briefing() -> bool:
    with fitness.connect() as db:
        last = db.execute("SELECT max(created) FROM briefings WHERE status='ok'").fetchone()[0] or 0
        newest = max(db.execute("SELECT coalesce(max(received),0) FROM reports").fetchone()[0],
                     db.execute("SELECT coalesce(max(received),0) FROM collector_reports").fetchone()[0])
    return newest > last


def daemon() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    fitness.connect().close()
    while True:
        nxt, first = _next_run(datetime.now(fitness.TZ))
        log.info("next briefing at %s%s", nxt.isoformat(), "" if first else " (only if new data)")
        time.sleep(max(1, (nxt - datetime.now(fitness.TZ)).total_seconds()))
        run_household(first)


def run_household(first=False):
    """Schedule independent briefings without sharing a wearer's data/context."""
    people=accounts.users() or [None]
    for person in people:
        if person and not person['active']: continue
        with accounts.as_user(person):
            if not new_data_since_last_briefing() and not first:
                continue
            with fitness.connect() as db:
                has_data=db.execute('SELECT EXISTS(SELECT 1 FROM reports) OR EXISTS(SELECT 1 FROM hrv_sessions)').fetchone()[0]
            if not has_data: continue
            for attempt in range(3):
                status=run()
                log.info("briefing run: %s",status)
                if status!='error': break
                time.sleep(900)



if __name__ == "__main__":
    if "--daemon" in sys.argv:
        daemon()
    else:
        print(run())
