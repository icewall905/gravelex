"""Wearer-specific retrospective analytics and decision support."""
from datetime import date, datetime, time, timedelta
from math import ceil, isfinite
from statistics import correlation, mean, median

MAX_BRIEFING_DAYS = 365
WINDOW = 41  # 42-day dashboard response includes the open local day.
MIN_COVERAGE = .75
METRICS = {
    "steps": ("Recorded steps", "steps"),
    "active_minutes": ("Recorded active minutes", "min"),
    "sleep_minutes": ("Watch-recorded sleep", "min"),
    "overnight_pulse": ("Low overnight pulse", "bpm"),
    "rmssd_ms": ("Comparable overnight HRV estimate", "ms"),
    "confirmed_load": ("Confirmed training load", "load units"),
    "weight_kg": ("Recorded weight", "kg"),
}
LINKS = (
    ("steps", "sleep_minutes", 1),
    ("steps", "overnight_pulse", 1),
    ("sleep_minutes", "overnight_pulse", 0),
    ("sleep_minutes", "rmssd_ms", 0),
    ("confirmed_load", "sleep_minutes", 1),
    ("confirmed_load", "overnight_pulse", 1),
)


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def day_minutes(day, tz):
    start = datetime.combine(day, time.min, tz).timestamp()
    end = datetime.combine(day + timedelta(days=1), time.min, tz).timestamp()
    return int((end - start) / 60)


def ranks(values):
    indexed = sorted(enumerate(values), key=lambda pair: pair[1])
    result = [0.0] * len(values)
    first = 0
    while first < len(indexed):
        last = first + 1
        while last < len(indexed) and indexed[last][1] == indexed[first][1]:
            last += 1
        rank = (first + last - 1) / 2
        for index, _ in indexed[first:last]:
            result[index] = rank
        first = last
    return result


def spearman(pairs):
    if len(pairs) < 7:
        return None
    xs, ys = zip(*pairs)
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    return correlation(ranks(xs), ranks(ys))


def quantile(values, proportion):
    ordered = sorted(values)
    position = (len(ordered) - 1) * proportion
    low, high = int(position), ceil(position)
    return ordered[low] + (position - low) * (ordered[high] - ordered[low])


def metric_summary(rows, key):
    recent = [r[key] for r in rows[-7:] if key in r]
    baseline = [r[key] for r in rows[-35:-7] if key in r]
    latest = next((r for r in reversed(rows) if key in r), None)
    label, unit = METRICS[key]
    result = {
        "label": label, "unit": unit, "recent_days": len(recent), "baseline_days": len(baseline),
        "latest": {"date": latest["date"], "value": latest[key]} if latest else None,
        "recent_median": round(median(recent), 1) if len(recent) >= 3 else None,
        "baseline_median": round(median(baseline), 1) if len(baseline) >= 10 else None,
        "baseline_middle_80_pct": None, "median_change": None,
    }
    if len(baseline) >= 10:
        result["baseline_middle_80_pct"] = [round(quantile(baseline, p), 1) for p in (.1, .9)]
    if len(recent) >= 3 and len(baseline) >= 10:
        result["median_change"] = round(median(recent) - median(baseline), 1)
    return result


def associations(rows):
    results = []
    split = len(rows) // 2
    for predictor, outcome, lag in LINKS:
        # Split by calendar date for replication, and keep the two samples disjoint.
        pairs = [(i, (rows[i-lag][predictor], row[outcome])) for i, row in enumerate(rows)
                 if i >= lag and predictor in rows[i-lag] and outcome in row
                 and not i-lag < split <= i]
        early = [pair for i, pair in pairs if i < split]
        late = [pair for i, pair in pairs if i >= split]
        a, b = spearman(early), spearman(late)
        combined = spearman(early + late)
        replicated = (a is not None and b is not None and abs(a) >= .35 and abs(b) >= .35
                      and abs(combined) >= .45 and a * combined > 0 and b * combined > 0)
        results.append({"predictor": predictor, "outcome": outcome, "lag_days": lag,
                        "pairs": len(pairs), "earlier_pairs": len(early), "later_pairs": len(late),
                        "status": ("exploratory_pattern" if replicated else
                                   "insufficient_pairs" if min(len(early), len(late)) < 7 else
                                   "no_consistent_pattern"),
                        "rank_correlation": round(combined, 2) if replicated else None})
    return results


def step_forecast(rows, today):
    """Test a four-week rolling median against the latest eligible total."""
    predictions, reference_errors = [], []
    for i, row in enumerate(rows[1:], 1):
        training = [r["steps"] for r in rows[max(0, i-28):i] if "steps" in r]
        previous = next((prior["steps"] for prior in reversed(rows[max(0, i-3):i]) if "steps" in prior), None)
        if len(training) >= 10 and previous is not None and "steps" in row:
            predictions.append(row["steps"] - median(training))
            reference_errors.append(abs(row["steps"] - previous))
    result = {"date": today.isoformat(), "status": "insufficient_history",
              "evaluation_days": len(predictions), "estimate": None, "typical_error_steps": None,
              "model_mae": None, "persistence_mae": None}
    if len(predictions) < 8:
        return result
    errors = [abs(e) for e in predictions]
    model_mae, persistence_mae = mean(errors), mean(reference_errors)
    result.update(model_mae=round(model_mae), persistence_mae=round(persistence_mae))
    training = [r["steps"] for r in rows[-28:] if "steps" in r]
    if len(training) < 10 or not any("steps" in r for r in rows[-3:]):
        result["status"] = "insufficient_recent_data"
    elif model_mae >= persistence_mae:
        result["status"] = "no_skill_over_persistence"
    else:
        result.update(status="available", estimate=round(median(training)),
                      typical_error_steps=round(median(errors)))
    return result


def weekly_goal(summary, today):
    intensity = (summary.get("fitness") or {}).get("intensity") or {}
    goal, observed = number(intensity.get("goal")), number(intensity.get("this_week"))
    if goal is None or observed is None:
        return None
    remaining = max(0, goal - observed)
    days = 7 - today.weekday()
    return {"target": goal, "observed": observed, "remaining_to_record": remaining,
            "days_left_including_today": days, "even_split_minutes": ceil(remaining / days)}


def qualified_days(summary, today, tz, length):
    dates = [today - timedelta(days=i) for i in range(length, 0, -1)]
    rows = {day.isoformat(): {"date": day.isoformat(), "expected_minutes": day_minutes(day, tz)}
            for day in dates}
    for item in summary.get("daily") or []:
        row = rows.get(item["date"])
        if row is None:
            continue
        row["recorded_minutes"] = min(row["expected_minutes"], item["minutes"])
        row["hr_minutes"] = min(row["expected_minutes"], item["hr_minutes"])
        for key, field in (("steps", "step_minutes"), ("active_minutes", "active_observed_minutes")):
            if item.get(field, 0) >= MIN_COVERAGE * row["expected_minutes"] and number(item.get(key)) is not None:
                row[key] = item[key]
        if item.get("overnight_hr_minutes", 0) >= 60 and number(item.get("resting_hr")) is not None:
            row["overnight_pulse"] = item["resting_hr"]

    recovery = summary.get("recovery") or {}
    for item in recovery.get("sleep_nights") or []:
        row = rows.get(item["night"])
        if row is not None and item["source"] in ("sessions", "daily_total") and number(item.get("sleep_s")) is not None:
            row["sleep_minutes"] = round(item["sleep_s"] / 60, 1)
            row["sleep_source"] = item["source"]
    series = (recovery.get("hrv_status") or {}).get("comparable_series")
    for item in recovery.get("nights") or []:
        row = rows.get(item["night"])
        if row is not None and series and item.get("comparable_series") == series and number(item.get("rmssd_ms")) is not None:
            row["rmssd_ms"] = item["rmssd_ms"]
    for item in summary.get("history") or []:
        row = rows.get(item["date"])
        if row is not None and item.get("complete") and number(item.get("load")) is not None:
            row["confirmed_load"] = item["load"]
    for item in (summary.get("weight") or {}).get("entries") or []:
        row = rows.get(item["date"])
        if row is not None and number(item.get("kg")) is not None:
            row["weight_kg"] = item["kg"]

    return list(rows.values())


def build(summary, tz):
    today = datetime.fromtimestamp(summary["now"], tz).date()
    days = qualified_days(summary, today, tz, WINDOW)
    recent = days[-7:]
    coverage = {"recorded_days": sum(r.get("recorded_minutes", 0) > 0 for r in recent),
                "usable_step_days": sum("steps" in r for r in recent),
                "recorded_sleep_nights": sum("sleep_minutes" in r for r in recent),
                "confirmed_load_days": sum("confirmed_load" in r for r in recent),
                "minute_coverage_pct": round(100 * sum(r.get("recorded_minutes", 0) for r in recent)
                                             / sum(r["expected_minutes"] for r in recent))}
    goal = weekly_goal(summary, today)
    receipt = ((summary.get("collection_health") or {}).get("transport") or {}).get("age_seconds")
    actions = []
    if receipt is None or receipt >= 86400:
        actions.append("check_sync")
    if coverage["usable_step_days"] < 4:
        actions.append("review_step_coverage")
    if coverage["confirmed_load_days"] < 4:
        actions.append("review_training_days")
    if goal and goal["remaining_to_record"]:
        actions.append("review_weekly_goal")
    return {
        "version": 1, "through": days[-1]["date"], "window_days": WINDOW,
        "coverage_last_7_days": coverage, "metrics": {key: metric_summary(days, key) for key in METRICS},
        "associations": associations(days), "steps_today_estimate": step_forecast(days, today),
        "weekly_intensity_goal": goal, "suggested_actions": actions, "days": days,
    }



def longer_history(days):
    """Dated evidence plus comparable, disjoint seven-day periods."""
    windows = []
    for end in range(len(days), 0, -7):
        segment = days[max(0, end-7):end]
        if not any(row.get("recorded_minutes") or any(key in row for key in METRICS) for row in segment):
            continue
        metrics = {}
        for key in METRICS:
            values = [row[key] for row in segment if key in row]
            if values:
                metrics[key] = {"n": len(values), "median": round(median(values), 1) if len(values) >= 4 else None}
        windows.append({
            "from": segment[0]["date"], "through": segment[-1]["date"],
            "days_with_minute_records": sum(row.get("recorded_minutes", 0) > 0 for row in segment),
            "metrics": metrics,
        })
    return {
        "from": days[0]["date"], "through": days[-1]["date"],
        "older_observed_days": [row for row in days[:-WINDOW]
                                if row.get("recorded_minutes") or any(key in row for key in METRICS)],
        "observed_weeks": windows,
        "comparable_past_weeks": comparable_weeks(windows, days[-1]["date"]),
    }


def comparable_weeks(windows, latest_date):
    """Rank historical weeks by differences in observed activity and sleep."""
    if not windows or windows[0]["through"] != latest_date:
        return []
    current = windows[0]["metrics"]
    base_scales = {"steps": 500, "sleep_minutes": 30, "overnight_pulse": 3}
    keys = [key for key in base_scales if current.get(key, {}).get("median") is not None]
    if len(keys) < 2:
        return []
    complete = [week for week in windows[1:] if all(
        week["metrics"].get(key, {}).get("median") is not None for key in keys)]
    if len(complete) < 4:
        return []
    scales = {}
    for key in keys:
        values = [week["metrics"][key]["median"] for week in complete]
        scales[key] = max(base_scales[key], quantile(values, .75) - quantile(values, .25))
    ranked = []
    for week in complete:
        differences = {key: round(week["metrics"][key]["median"] - current[key]["median"], 1)
                       for key in keys}
        distance = mean(abs(differences[key]) / scales[key] for key in keys)
        if distance <= 1:
            ranked.append((distance, {
                "from": week["from"], "through": week["through"],
                "historical_minus_recent": differences,
            }))
    ranked.sort(key=lambda item: item[0])
    return [week for _, week in ranked[:3]]
