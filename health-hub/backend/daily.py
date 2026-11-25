"""Per-local-day activity and heart-rate totals from canonical minutes.

Dashboard charts and the Android client read these instead of raw minutes, so
long ranges stay small and complete. Missing minutes are counted, never zeroed:
``minutes`` and ``hr_minutes`` say how much of each day was observed.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from datetime import date, datetime, time, timedelta
from typing import Any

FIELD_LIMITS = {"active_kcal": 10000, "resting_kcal": 10000, "distance_m": 100000}


def _day_starts(first: date, last: date, tz) -> list[tuple[int, date]]:
    """Local midnights as epoch seconds; DST days are 23 or 25 hours long."""
    out, day = [], first
    while day <= last + timedelta(days=1):
        out.append((int(datetime.combine(day, time.min, tz).timestamp()), day))
        day += timedelta(days=1)
    return out


def _num(value: Any, limit: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value if 0 <= value <= limit else None


def rollup(db, start_day: date, end_day: date, tz, now: int) -> list[dict[str, Any]]:
    """One row per local day in [start_day, end_day], including empty days."""
    bounds = _day_starts(start_day, end_day, tz)
    starts = [b[0] for b in bounds]
    days: dict[date, dict[str, Any]] = {}
    hr_values: dict[date, list[int]] = {}
    night_hr: dict[date, list[int]] = {}
    for d in (b[1] for b in bounds[:-1]):
        days[d] = {"date": d.isoformat(), "minutes": 0, "steps": 0, "active_minutes": 0,
                   "step_minutes": 0, "active_observed_minutes": 0, "overnight_hr_minutes": 0,
                   "active_kcal": None, "resting_kcal": None, "distance_m": None,
                   "hr_minutes": 0, "hr_min": None, "hr_avg": None, "hr_max": None, "resting_hr": None}
    rows = db.execute(
        "SELECT ts,hr,steps,active,json_extract(payload,'$.active_kcal') ak,"
        " json_extract(payload,'$.resting_kcal') rk, json_extract(payload,'$.distance_m') dm"
        " FROM minutes WHERE ts>=? AND ts<? AND ts<=? ORDER BY ts", (starts[0], starts[-1], now + 300))
    for ts, hr, steps, active, ak, rk, dm in rows:
        i = bisect_right(starts, ts) - 1
        if i < 0 or i >= len(bounds) - 1:
            continue
        d = bounds[i][1]
        row = days[d]
        row["minutes"] += 1
        if isinstance(steps, int) and 0 <= steps <= 10000:
            row["steps"] += steps
            row["step_minutes"] += 1
        if active in (0, 1):
            row["active_observed_minutes"] += 1
        if active == 1:
            row["active_minutes"] += 1
        for key, value in (("active_kcal", ak), ("resting_kcal", rk), ("distance_m", dm)):
            value = _num(value, FIELD_LIMITS[key])
            if value is not None:
                row[key] = (row[key] or 0) + value
        if isinstance(hr, int) and 25 <= hr <= 250:
            hr_values.setdefault(d, []).append(hr)
            if datetime.fromtimestamp(ts, tz).hour < 6:
                night_hr.setdefault(d, []).append(hr)
    for d, row in days.items():
        values = hr_values.get(d)
        if values:
            row.update(hr_minutes=len(values), hr_min=min(values), hr_max=max(values),
                       hr_avg=round(sum(values) / len(values), 1))
        # Lowest sustained pulse: 10th percentile of 00-06 readings, needs 20.
        night = sorted(night_hr.get(d, []))
        row["overnight_hr_minutes"] = len(night)
        if len(night) >= 20:
            row["resting_hr"] = night[len(night) // 10]
        for key in ("active_kcal", "resting_kcal", "distance_m"):
            if row[key] is not None:
                row[key] = round(row[key], 1)
        if row["minutes"] == 0:
            row["steps"] = None
            row["active_minutes"] = None
    return [days[d] for d in sorted(days)]


def intraday(db, day: date, tz, now: int) -> dict[str, Any]:
    """Minute HR/steps/activity for one local day plus 15-minute step buckets."""
    start = int(datetime.combine(day, time.min, tz).timestamp())
    end = int(datetime.combine(day + timedelta(days=1), time.min, tz).timestamp())
    points = []
    buckets: dict[int, int] = {}
    for ts, hr, steps, active, intensity, distance in db.execute(
            "SELECT ts,hr,steps,active,json_extract(payload,'$.intensity'),"
            "json_extract(payload,'$.distance_m') FROM minutes"
            " WHERE ts>=? AND ts<? AND ts<=? ORDER BY ts", (start, end, now + 300)):
        points.append({"ts": ts, "hr": hr if isinstance(hr, int) and 25 <= hr <= 250 else None,
                       "steps": steps, "active": active,
                       "intensity": intensity if isinstance(intensity, (int, float)) else None,
                       "distance_m": distance if isinstance(distance, (int, float)) else None})
        if isinstance(steps, int) and steps > 0:
            key = start + ((ts - start) // 900) * 900
            buckets[key] = buckets.get(key, 0) + steps
    sleep = [dict(r) for r in db.execute(
        "SELECT start,seconds,kind FROM sleep_sessions WHERE start<? AND start+seconds>? ORDER BY start",
        (end, start - 12 * 3600))]
    return {"date": day.isoformat(), "start": start, "end": end, "points": points,
            "steps_15min": [{"ts": k, "steps": v} for k, v in sorted(buckets.items())],
            "sleep": sleep}
