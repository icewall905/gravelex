"""Transparent observation layer for monitor data.

This module intentionally sits beside the recovery/HRV model.  A watch can
report a pulse summary even when its PPI recording fails the experimental HRV
quality gates.  Such a value is useful as an *overnight spot pulse*, but it is
not a validated resting heart rate and never becomes a readiness input here.

``build`` accepts raw rows of ``{"ts": ..., "payload": {...}}`` and returns
nightly pulse observations plus diagnostics for pulse, breathing and manual
stress monitors.  Timestamps are measurement timestamps; receipt timestamps
are only included when the source supplied one.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

try:
    import hrv
except ImportError:  # pragma: no cover - allows documentation import
    hrv = None


NIGHT_START_HOUR = 18
NIGHT_END_HOUR = 14


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _night_of(ts: float, tz: ZoneInfo) -> date | None:
    local = datetime.fromtimestamp(ts, tz)
    if local.hour >= NIGHT_START_HOUR:
        return local.date() + timedelta(days=1)
    if local.hour < NIGHT_END_HOUR:
        return local.date()
    return None


def _payload(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    payload = row.get("payload", row)
    return payload if isinstance(payload, dict) else None


def _context(payload: dict[str, Any]) -> str:
    return "scheduled" if payload.get("context") == "scheduled" or payload.get("scheduled") is True else "manual"


def _reported_hr(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    # Preserve firmware naming while accepting the snake-case form used by
    # newer exports.  Zero is unknown, not a physiological value.
    for key in ("reportedHR", "reported_hr", "mean_reported_hr"):
        if key in payload:
            value = payload[key]
            if not _finite(value) or not 1 <= float(value) <= 300:
                return None, "reported_hr_invalid"
            return float(value), None
    return None, "reported_hr_missing"


def _method(payload: dict[str, Any]) -> str:
    value = payload.get("reported_hr_method") or payload.get("hr_method") or payload.get("method")
    base = str(value) if value else "reportedHR"
    # Firmware/collector/source changes are not silently pooled into one
    # comparable method, even when both exports use the same HR field.
    identity = tuple(str(payload.get(key) or "unknown") for key in ("firmware", "collector_version", "source"))
    return base + ":" + ":".join(identity)


def _integrity(payload: dict[str, Any]) -> str | None:
    if "hr_valid" in payload and (not _finite(payload["hr_valid"]) or float(payload["hr_valid"]) <= 0):
        return "hr_valid_invalid"
    for key in ("hr_events", "heart_rate_events"):
        if key in payload and (not _finite(payload[key]) or float(payload[key]) <= 0):
            return "hr_events_invalid"
    if "hr_valid" in payload and "hr_events" in payload and float(payload["hr_events"]) < float(payload["hr_valid"]):
        return "hr_events_less_than_hr_valid"
    if "duration_ms" in payload and (not _finite(payload["duration_ms"]) or float(payload["duration_ms"]) <= 0):
        return "duration_invalid"
    if "hr_sum" in payload and "hr_valid" in payload and (not _finite(payload["hr_sum"]) or float(payload["hr_sum"]) <= 0):
        return "hr_sum_invalid"
    if "hr_sum" in payload and "hr_valid" in payload:
        value, _ = _reported_hr(payload)
        if value is not None and abs(value - float(payload["hr_sum"]) / float(payload["hr_valid"])) > 0.005 + 1e-9:
            return "reported_hr_mean_inconsistent"
    return None


def _diag(received: int, eligible: int, reasons: Counter[str], *, latest_receipt: float | None = None,
          last_measured: float | None = None, now: float | None = None) -> dict[str, Any]:
    out = {"received": received, "eligible": eligible, "excluded": received - eligible,
           "exclusion_reasons": dict(sorted(reasons.items()))}
    if latest_receipt is not None:
        out["latest_receipt_ts"] = latest_receipt
    if last_measured is not None:
        out["last_measured_at"] = last_measured
        out["age_seconds"] = max(0.0, float(now) - last_measured) if now is not None else None
    return out


def _receipt_ts(row: dict[str, Any], payload: dict[str, Any]) -> float | None:
    for key in ("received_ts", "receipt_ts", "received_at", "uploaded_at"):
        value = row.get(key, payload.get(key))
        if _finite(value):
            return float(value)
    return None


def build(sessions: list[dict[str, Any]], now: float | None = None, tz: str | ZoneInfo | None = None) -> dict[str, Any]:
    """Build transparent monitor observations from raw exported sessions.

    ``now`` bounds future records.  ``tz`` may be a ZoneInfo or an IANA name;
    omitted timezone is UTC.  Every excluded row contributes one concrete
    diagnostic reason.  No medical or motion threshold is inferred here.
    """
    zone = ZoneInfo(tz) if isinstance(tz, str) else (tz or timezone.utc)
    now = float(now) if _finite(now) else datetime.now(timezone.utc).timestamp()
    pulse_groups: dict[date, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    pulse_reasons: Counter[str] = Counter()
    pulse_received = 0
    pulse_eligible = 0
    latest_receipt: float | None = None
    breathing_reasons: Counter[str] = Counter()
    stress_reasons: Counter[str] = Counter()
    breathing_received = breathing_eligible = 0
    stress_received = stress_eligible = 0
    stress_days: set[str] = set()
    stress_qualified_days: set[str] = set()
    stress_series: dict[str, dict[str, int]] = defaultdict(lambda: {"received": 0, "eligible": 0})

    for row in sessions if isinstance(sessions, list) else []:
        payload = _payload(row)
        if payload is None:
            continue
        ts = row.get("ts", payload.get("ts")) if isinstance(row, dict) else None
        valid_ts = _finite(ts) and 946684800 <= float(ts) <= now
        context = _context(payload)
        quality = None
        if hrv is not None:
            try:
                quality = hrv.analyze_session(payload)
            except (TypeError, ValueError, KeyError):
                quality = None
        # Pulse monitor: only scheduled overnight recordings are observations.
        value, reason = _reported_hr(payload)
        if value is not None or reason != "reported_hr_missing":
            pulse_received += 1
            if not valid_ts:
                pulse_reasons["timestamp_invalid_or_future"] += 1
            elif context != "scheduled":
                pulse_reasons["context_not_scheduled"] += 1
            else:
                night = _night_of(float(ts), zone)
                if night is None:
                    pulse_reasons["outside_night_window"] += 1
                else:
                    integrity_reason = _integrity(payload)
                    if integrity_reason:
                        pulse_reasons[integrity_reason] += 1
                    elif value is None:
                        pulse_reasons[reason or "reported_hr_missing"] += 1
                    else:
                        pulse_eligible += 1
                        receipt = _receipt_ts(row, payload)
                        latest_receipt = max(latest_receipt or receipt, receipt) if receipt is not None else latest_receipt
                        pulse_groups[night][_method(payload)].append({"ts": float(ts), "value": value, "payload": payload})

        # Raw exports do not carry derived respiration. Count every scheduled
        # night capture received, then qualify only from the HRV analyser.
        if valid_ts and context == "scheduled" and _night_of(float(ts), zone) is not None:
            breathing_received += 1
            resp = quality.get("respiration") if quality else None
            if not quality or quality.get("status") != "experimental":
                breathing_reasons[quality.get("status", "quality_insufficient") if quality else "quality_insufficient"] += 1
            elif not isinstance(resp, dict) or resp.get("reliable") is not True:
                breathing_reasons["strict_qualification_missing"] += 1
            elif not quality.get("motion", {}).get("eligible", False):
                breathing_reasons["motion_ineligible"] += 1
            else:
                breathing_eligible += 1

        # Manual stress diagnostics deliberately do not copy or score values.
        # Every valid manual capture is received; quality remains separated by
        # the analyser's source/metric/algorithm identity.
        if context == "manual" and valid_ts:
            stress_received += 1
            day = datetime.fromtimestamp(float(ts), zone).date().isoformat()
            stress_days.add(day)
            series = None
            if quality:
                series = "|".join(str(quality.get(key) or "unknown") for key in ("source", "metric", "algorithm_version"))
                stress_series[series]["received"] += 1
            qualified = bool(quality and quality.get("status") == "experimental" and quality.get("experimental_rmssd_ms") is not None
                            and quality.get("motion", {}).get("eligible", False))
            if qualified:
                stress_eligible += 1
                stress_qualified_days.add(day)
                if series is not None:
                    stress_series[series]["eligible"] += 1
            else:
                stress_reasons[quality.get("status", "quality_insufficient") if quality else "quality_insufficient"] += 1
        elif context == "manual" and not valid_ts:
            stress_reasons["timestamp_invalid_or_future"] += 1

    nights = []
    for night, groups in sorted(pulse_groups.items()):
        method = min(groups, key=lambda key: (-len(groups[key]), key))
        selected = groups[method]
        excluded = sum(len(v) for k, v in groups.items() if k != method)
        if excluded:
            pulse_eligible -= excluded
            pulse_reasons["mixed_measurement_method"] += excluded
        actual_ts = min(x["ts"] for x in selected)
        nights.append({"night": night.isoformat(), "label": "overnight spot pulse", "value": round(median(x["value"] for x in selected), 1),
                       "pulse": round(median(x["value"] for x in selected), 1), "observed_at": actual_ts,
                       "timestamps": [x["ts"] for x in sorted(selected, key=lambda x: x["ts"])], "observations": len(selected),
                       "method": method, "excluded_mixed_methods": excluded,
                       "validated": False, "resting": False, "proven_resting": False,
                       "qualifies_for_readiness": False, "source_validation": "unvalidated"})
    scheduled_measured = max((float(row.get("ts", _payload(row).get("ts"))) for row in sessions if isinstance(row, dict)
                              and _payload(row) is not None and _context(_payload(row)) == "scheduled"
                              and _finite(row.get("ts", _payload(row).get("ts")))
                              and 946684800 <= float(row.get("ts", _payload(row).get("ts"))) <= now
                              and _night_of(float(row.get("ts", _payload(row).get("ts"))), zone) is not None), default=None)
    manual_measured = max((float(row.get("ts", _payload(row).get("ts"))) for row in sessions if isinstance(row, dict)
                           and _payload(row) is not None and _context(_payload(row)) == "manual"
                           and _finite(row.get("ts", _payload(row).get("ts")))
                           and 946684800 <= float(row.get("ts", _payload(row).get("ts"))) <= now), default=None)
    diagnostics = {"pulse": _diag(pulse_received, pulse_eligible, pulse_reasons, latest_receipt=latest_receipt,
                                    last_measured=scheduled_measured, now=now),
                   "breathing": _diag(breathing_received, breathing_eligible, breathing_reasons,
                                       last_measured=scheduled_measured, now=now),
                   "stress": _diag(stress_received, stress_eligible, stress_reasons,
                                   last_measured=manual_measured, now=now)}
    diagnostics["stress"].update({"received_manual_days": len(stress_days), "qualified_manual_days": len(stress_qualified_days),
                                   "status": "diagnostics_only", "score_used": False,
                                   "series": dict(stress_series)})
    return {"overnight_spot_pulse": nights, "nightly_pulse": nights, "diagnostics": diagnostics,
            "readiness_inputs": [], "source_validation": "unvalidated"}
