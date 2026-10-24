"""Bounded estimates from stock firmware observations.

These values are deliberately separate from the experimental HRV/recovery
model.  The pulse input is the firmware's reported pulse summary; PPI samples
are used only for an explicitly unverified variability diagnostic.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

try:
    import hrv
except ImportError:  # pragma: no cover
    hrv = None

NIGHT_START, NIGHT_END = 18, 14
REQUIRED_BASELINE = 3
METHOD = "overnight_pulse_strain_v1"


def _num(v: Any) -> bool:
    try:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))
    except (OverflowError, ValueError):
        return False


def _night(ts: float, zone: ZoneInfo) -> date | None:
    local = datetime.fromtimestamp(ts, zone)
    if local.hour >= NIGHT_START:
        return local.date() + timedelta(days=1)
    if local.hour < NIGHT_END:
        return local.date()
    return None


def _payload(row: Any) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        return None
    value = row.get("payload", row)
    return value if isinstance(value, dict) else None


def _reported(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    for key in ("reportedHR", "reported_hr", "mean_reported_hr"):
        if key in payload:
            value = payload[key]
            if not _num(value) or not 30 <= float(value) <= 220:
                return None, "pulse_invalid"
            return float(value), key
    return None, "pulse_missing"


def _identity(payload: dict[str, Any], field: str) -> tuple[str, str, str]:
    firmware = payload.get("firmware")
    firmware = firmware.strip() if isinstance(firmware, str) and firmware.strip() else "unknown"
    raw_collector = payload.get("collector_version")
    collector = (raw_collector.strip() if isinstance(raw_collector, str) and raw_collector.strip()
                 else str(raw_collector) if _num(raw_collector) else "unknown")
    # Collector 150..153 used the same filtered-BPM mean contract. Pooling
    # that narrow range is allowed only when the source counters prove it.
    try:
        version = int(collector)
    except ValueError:
        version = -1
    if (150 <= version <= 153 and field == "mean_reported_hr"
            and _num(payload.get("hr_sum")) and _num(payload.get("hr_valid"))):
        return firmware, "collector_contract150_153", "pulse_api:filtered_bpm_event_mean_v1"
    return firmware, collector, field


def _integrity(payload: dict[str, Any]) -> str | None:
    if _num(payload.get("vibration_samples")) and float(payload["vibration_samples"]) > 0:
        return "vibration_samples_present"
    if not _num(payload.get("hr_valid")) or float(payload["hr_valid"]) < 60 or float(payload["hr_valid"]) != int(payload["hr_valid"]):
        return "hr_valid_insufficient"
    if "hr_events" in payload and (not _num(payload["hr_events"]) or float(payload["hr_events"]) < float(payload["hr_valid"])):
        return "hr_events_insufficient"
    if "hr_sum" in payload and "mean_reported_hr" in payload:
        if (not _num(payload.get("hr_sum")) or not _num(payload.get("mean_reported_hr"))
                or abs(float(payload["mean_reported_hr"]) - float(payload["hr_sum"]) / float(payload["hr_valid"])) > 0.005 + 1e-9):
            return "reported_hr_mean_inconsistent"
    duration = payload.get("duration_s")
    if duration is None and _num(payload.get("duration_ms")):
        duration = float(payload["duration_ms"]) / 1000
    if not _num(duration) or float(duration) < 120:
        return "duration_insufficient"
    return None


def _clip(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 1)


def _sleep_score(sleep: Any) -> float | None:
    if not isinstance(sleep, dict):
        return None
    value = sleep.get("score")
    return float(value) if _num(value) and 0 <= float(value) <= 100 else None


def _training_component(training: Any, now: float, zone: ZoneInfo) -> tuple[float | None, str]:
    if not isinstance(training, dict) or training.get("status") != "ready":
        return None, "training load is not ready"
    try:
        day = date.fromisoformat(str(training["date"]))
        age = (datetime.fromtimestamp(now, zone).date() - day).days
        if not _num(training.get("chronic")) or not _num(training.get("acute")):
            raise ValueError
        chronic, acute = float(training["chronic"]), float(training["acute"])
        if age < 0 or age > 1 or chronic <= 0 or acute < 0 or not math.isfinite(chronic + acute):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return None, "training load is stale, invalid, or has no chronic baseline"
    return _clip(50 + 100 * (chronic - acute) / chronic), ""


def build(sessions: list[dict[str, Any]], monitor_nights: Any, sleep: dict[str, Any],
          training_latest: dict[str, Any] | None, now: float, tz: str | ZoneInfo = "UTC") -> dict[str, Any]:
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    now = float(now) if _num(now) else datetime.now(timezone.utc).timestamp()
    rows = list(sessions) if isinstance(sessions, list) else []
    # Accept monitor-night containers only when they retain the raw payload;
    # never turn an already-derived ``pulse`` value into a new observation.
    if isinstance(monitor_nights, list):
        rows.extend(row for row in monitor_nights if _payload(row) is not None)
    groups: dict[tuple[date, tuple[str, str, str]], list[tuple[float, float, bool, str]]] = defaultdict(list)
    rejected: dict[str, int] = defaultdict(int)
    variability: list[dict[str, Any]] = []
    seen: set[tuple[float, tuple[str, str, str], float]] = set()
    for row in rows:
        payload = _payload(row)
        if payload is None:
            continue
        ts = row.get("ts", payload.get("ts"))
        if not _num(ts) or float(ts) < 946684800 or float(ts) > now:
            rejected["future_or_invalid_timestamp"] += 1
            continue
        context = "scheduled" if payload.get("context") == "scheduled" or payload.get("scheduled") is True else "manual"
        if hrv is not None:
            try:
                diagnostic = hrv.analyze_session(payload)
            except (TypeError, ValueError, KeyError):
                diagnostic = None
            value_ms = diagnostic.get("diagnostic_delivered_ppi_variation_ms") if isinstance(diagnostic, dict) else None
            if (isinstance(diagnostic, dict) and diagnostic.get("status") == "beat_continuity_unverified"
                    and _num(value_ms)):
                variability.append({"ts": float(ts), "value_ms": float(value_ms),
                                    "source": diagnostic.get("source", "unknown"),
                                    "context": context, "metric": "delivered_ppi_variation_unverified",
                                    "status": "beat_continuity_unverified",
                                    "algorithm_version": diagnostic.get("algorithm_version", "unknown")})
        if payload.get("context") not in ("scheduled",) and payload.get("scheduled") is not True:
            continue
        night = _night(float(ts), zone)
        value, field = _reported(payload)
        if night is None or value is None:
            if value is None:
                rejected[field or "pulse_missing"] += 1
            continue
        reason = _integrity(payload)
        ident = _identity(payload, field or "reported_hr")
        if reason:
            rejected[reason] += 1
            continue
        key = (float(ts), ident, value)
        if key in seen:
            continue
        seen.add(key)
        low_confidence = True  # stock pulse has no validated quiet/resting gate
        groups[(night, ident)].append((value, float(ts), low_confidence, str(payload.get("collector_version") or "unknown")))

    # Pick the identity represented by the newest valid night; never pool identities.
    if groups:
        current_ident = max(groups, key=lambda k: max(x[1] for x in groups[k]))[1]
    else:
        current_ident = None
    points = []
    for (night, ident), values in sorted(groups.items()):
        if ident != current_ident:
            continue
        points.append({"night": night.isoformat(), "pulse": round(median(x[0] for x in values), 1),
                       "measured_at": min(x[1] for x in values), "observed_at": min(x[1] for x in values),
                       "low_confidence": any(x[2] for x in values), "collector_versions": sorted({x[3] for x in values}),
                       "method_identity": ident})
    points.sort(key=lambda x: x["night"])
    latest = points[-1] if points else None
    today = datetime.fromtimestamp(now, zone).date()
    prior = [p for p in points if latest and p is not latest
             and 0 < (date.fromisoformat(latest["night"]) - date.fromisoformat(p["night"])).days <= 28]
    baseline_values = [p["pulse"] for p in prior]
    known_identity = bool(current_ident and all(str(v).lower() not in ("unknown", "none", "null", "") for v in current_ident))
    baseline_days = len(baseline_values) if known_identity else 0
    baseline = median(baseline_values) if baseline_days >= REQUIRED_BASELINE else None
    mad = median([abs(x - baseline) for x in baseline_values]) if baseline is not None else None
    pulse_score = None if latest is None or baseline is None else _clip(50 - 20 * (latest["pulse"] - baseline) / max(3, 1.4826 * mad))
    pulse_status = "ready" if pulse_score is not None else "baseline_building"
    pulse_reason = (f"baseline median {baseline:.1f}, latest delta {latest['pulse'] - baseline:+.1f} bpm"
                    if pulse_score is not None and baseline is not None and latest
                    else f"needs {REQUIRED_BASELINE} earlier comparable nights with known firmware and collector")
    if latest and not known_identity:
        pulse_reason = "Firmware or collector identity is unknown; earlier nights cannot establish a comparable baseline"
    pulse_identity = ({"firmware": current_ident[0], "collector_version": current_ident[1], "field": current_ident[2]}
                      if current_ident else None)
    pulse = {"latest": latest, "points": points,
             "baseline_days": baseline_days, "required_days": REQUIRED_BASELINE,
             "status": pulse_status, "reason": pulse_reason, "method_identity": pulse_identity,
             "confidence": "low_stock_proxy", "provisional": len(baseline_values) < 14}
    measured_at = latest["measured_at"] if latest else None
    age = max(0.0, now - measured_at) if measured_at is not None else None
    strain_score = None if pulse_score is None or age is None or age > 36 * 3600 else round(100 - pulse_score)
    strain_reason = (f"baseline median {baseline:.1f}, latest delta {latest['pulse'] - baseline:+.1f} bpm"
                     if strain_score is not None and baseline is not None and latest else
                     pulse_reason if pulse_score is None else "Pulse observation is older than 36 hours")
    strain = {"score": strain_score, "status": "ready" if strain_score is not None else "insufficient",
              "context": "scheduled", "measured_at": measured_at, "age_seconds": age,
              "reason": strain_reason, "expires_at": measured_at + 36 * 3600 if measured_at is not None else None,
              "baseline_days": baseline_days, "required_days": REQUIRED_BASELINE,
              "estimated": True, "confidence": "low_stock_proxy", "method": METHOD}
    components: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    readiness_pulse_score = pulse_score if latest and date.fromisoformat(latest["night"]) == today else None
    if readiness_pulse_score is not None:
        components["resting_hr"] = {"score": readiness_pulse_score, "estimated": True, "provisional": True}
    else:
        missing.append("resting_hr: stock pulse estimate unavailable")
    ss = _sleep_score(sleep)
    if ss is not None:
        components["sleep"] = {"score": ss, "estimated": True, "provisional": True}
    else:
        missing.append("sleep: no actual sleep score")
    training_score, training_reason = _training_component(training_latest, now, zone)
    if training_score is not None:
        components["training_load"] = {"score": training_score, "estimated": True, "provisional": True}
    else:
        missing.append("training_load: " + training_reason)
    weights = {"sleep": .5, "resting_hr": .3, "training_load": .2}
    identity = {"formula_version": "readiness-stock-v1", "input_keys": sorted(components),
                "comparable_series": {"firmware": current_ident[0], "collector_version": current_ident[1], "field": current_ident[2]} if current_ident else None}
    comp_key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    coverage = sum(weights[k] for k in components)
    readiness = {"score": None, "status": "insufficient", "components": components, "weights": weights,
                 "formula_version": "readiness-stock-v1", "comparable_series": identity["comparable_series"],
                 "method_identity": identity, "comparability_key": comp_key, "components_count": len(components),
                 "total_components": 3, "effective_weight_coverage": coverage, "missing": missing,
                 "provisional": True, "estimated": True, "available_count": 3,
                 "confidence": "low_stock_proxy",
                 "method": "Custom weighted mean: sleep 50%, overnight pulse proxy 30%, confirmed training 20%; available weights renormalized. Pulse proxy compares current night with earlier comparable nights using median/MAD and a 3 bpm scale floor; HRV and breathing excluded.",
                 "reason": "Needs at least two stock inputs including sleep"}
    if len(components) >= 2 and "sleep" in components:
        total = sum(weights[k] * components[k]["score"] for k in components)
        readiness.update(score=round(total / coverage), status="estimated", reason="Stock firmware estimate; missing inputs omitted")
    elif len(components) == 1 and "sleep" in components:
        readiness["sleep_based_score"] = components["sleep"]["score"]
        readiness["reason"] = "Only sleep is available; overall readiness is withheld"
    variability_out = {"points": variability, "latest": variability[-1] if variability else None,
                       "method": "delivered_ppi_variation_unverified", "used_for_readiness": False}
    return {"mode": "stock_firmware_estimates", "estimated": True, "pulse": pulse, "strain": strain,
            "readiness": readiness, "variability": variability_out, "rejected": dict(rejected)}
