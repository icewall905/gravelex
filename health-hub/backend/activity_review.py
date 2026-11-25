"""Minute evidence for completed activity reviews."""
import math


FIELDS = {
    "hr": (25, 300), "peak_hr": (25, 300), "hr_seconds": (1, 60),
    "distance_m": (0, 2400), "gps_seconds": (1, 60), "steps": (0, 10000),
    "active": (0, 1), "elevation_m": (-12000, 12000),
}
MAX_SECONDS = 172800


def _number(value, low, high, label, integer=False):
    if (type(value) not in (int, float) or not low <= value <= high
            or (integer and type(value) is not int)):
        raise ValueError(f"Invalid {label}.")
    return value


def _duration(value):
    return _number(value, 1, MAX_SECONDS, "activity duration", integer=True)


def _timeline(seconds, rows, clock="elapsed"):
    fields = [key for key in FIELDS if any(key in row for row in rows)]
    return {
        "clock": clock,
        "columns": ["minute", "seconds", *fields],
        "minutes": [[i + 1, min(60, seconds - i * 60), *(row.get(key) for key in fields)]
                    for i, row in enumerate(rows)],
    }


def from_phone(body, sports):
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in sports:
        raise ValueError("Invalid activity type.")
    seconds = _duration(body.get("seconds"))
    active = _number(body.get("active_seconds"), 0, seconds, "active duration", integer=True)
    rows = body.get("minutes")
    if not isinstance(rows, list) or len(rows) != math.ceil(seconds / 60):
        raise ValueError("Provide one entry for each elapsed minute.")
    for row in rows:
        if not isinstance(row, dict) or row.keys() - FIELDS.keys():
            raise ValueError("Invalid minute data.")
        for key, value in row.items():
            _number(value, *FIELDS[key], key)
    source = "manual" if body.get("manual") is True else "phone recording"
    if source == "manual" and any(rows):
        raise ValueError("Manual activities cannot include recorded samples.")
    data = {"kind": kind, "elapsed_seconds": seconds, "active_seconds": active,
            "source": source, **_timeline(seconds, rows)}
    for key, bounds in {"distance_m": (0, 40 * seconds), "effort": (1, 10), "strength_sets": (0, 10000)}.items():
        if key in body:
            data[key] = _number(body[key], *bounds, key)
    return data


def from_hub(db, workout, phone=None):
    seconds = _duration(workout["seconds"])
    data = {"kind": workout["kind"], "elapsed_seconds": seconds, "source": workout.get("source") or "watch",
            "effort": workout.get("rpe")}
    if phone is not None:
        seconds = _duration(phone["seconds"])
        active = _duration(phone["active_seconds"])
        data.update(elapsed_seconds=seconds, source="synced phone recording")
        rows = [{} for _ in range(math.ceil(active / 60))]
        for offset, bpm, coverage in phone.get("heart", []):
            if 0 <= offset // 60 < len(rows):
                rows[offset // 60] = {"hr": bpm, "hr_seconds": coverage}
        data.update(active_seconds=active, distance_m=phone.get("distance_m"), **_timeline(active, rows, "active"))
    else:
        if data["source"] == "manual":
            return {**data, **_timeline(seconds, [{} for _ in range(math.ceil(seconds / 60))])}
        start = workout["start"]
        rows = [{} for _ in range(math.ceil(seconds / 60))]
        for ts, hr, steps, active in db.execute(
                "SELECT ts,hr,steps,active FROM minutes WHERE ts>=? AND ts<? ORDER BY ts",
                (start, start + seconds)):
            row = rows[(ts - start) // 60]
            if isinstance(hr, int) and 25 <= hr <= 250:
                row["hr"] = hr
            if isinstance(steps, int) and steps >= 0:
                row["steps"] = steps
            if active in (0, 1):
                row["active"] = active
        data.update(_timeline(seconds, rows))
    return data


def verified_timing(evidence):
    def format_duration(seconds):
        hours, remaining = divmod(seconds, 3600)
        minutes, seconds = divmod(remaining, 60)
        return f"{hours} h {minutes} min {seconds} s" if hours else f"{minutes} min {seconds} s"

    elapsed = evidence["elapsed_seconds"]
    parts = [f"{format_duration(elapsed)} elapsed"]
    active = evidence.get("active_seconds")
    if active is not None:
        parts.append(f"{format_duration(active)} active")
        if active < elapsed:
            parts.append(f"{format_duration(elapsed - active)} outside active time")
    return " · ".join(parts)


PROMPT = (
    "Review this single completed activity using workout_context. Inspect every supplied minute row and "
    "cover the full session from start to finish. The columns identify row values; null means missing, "
    "never zero. HR is the observed average or a watch reading, and only peak_hr is a measured peak. "
    "Heart-rate seconds and GPS seconds measure coverage, and active is the watch activity flag. "
    "Phone minute distances are estimates; compare rates only when GPS coverage is similar. "
    "Treat partial and sparsely sampled minutes as such. A missing minute gives no evidence of a pause. "
    "On the active clock, pauses were removed and cannot be located. "
    "The app displays verified timing totals separately, so do not repeat or convert the overall time or estimate pause duration. "
    "Describe observed changes with minute numbers, group consecutive minutes where appropriate, and give one practical takeaway. "
    "Avoid assigning an intensity zone without an athlete-specific reference. For manual entries or missing metrics, "
    "state the limits. Do not infer medical conditions, create calendar plans, or save notes. Return an empty options array."
)
