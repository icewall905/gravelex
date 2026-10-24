"""Bounded read-only API for external clients.

The application owns wiring and token storage.  This module only adapts an
injected dashboard/history provider and delegates bearer authorization to
``api_tokens.authorize``.
"""
from __future__ import annotations

import base64
import binascii
import json
import math
import time
import accounts
from datetime import date, datetime, timezone
from typing import Any

from flask import Blueprint, jsonify, request

try:
    import fitness
    import workout_edits
except ImportError:  # pragma: no cover
    fitness = None
    workout_edits = None

try:
    import api_tokens
except ImportError:  # pragma: no cover - injected by the application/tests
    api_tokens = None


MAX_RANGE = 365 * 86400
DEFAULT_RANGE = 7 * 86400
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
RESOURCES = {"minutes", "workouts", "sleep", "oxygen", "weights", "hrv-sessions"}


def _auth(scope: str):
    if api_tokens is None:
        return {"error": "API authorization unavailable"}, 503
    result = api_tokens.authorize(scope)
    return result


def _finite_int(value: str | None, name: str) -> int:
    if value is None or not value.isdigit():
        raise ValueError(f"{name} must be an integer")
    parsed = int(value)
    if parsed < 0 or parsed > 4102444800:
        raise ValueError(f"invalid {name}")
    return parsed


def _bounds(default_range: tuple[int, int] | None = None) -> tuple[int, int, int]:
    default_end = default_range[1] if default_range else int(time.time())
    default_start = default_range[0] if default_range else default_end - DEFAULT_RANGE
    end = _finite_int(request.args.get("end"), "end") if request.args.get("end") else default_end
    start = _finite_int(request.args.get("start"), "start") if request.args.get("start") else default_start
    limit = _finite_int(request.args.get("limit"), "limit") if request.args.get("limit") else DEFAULT_LIMIT
    if start < 0 or end > 4102444800 or limit < 1 or limit > MAX_LIMIT or start >= end or end - start > MAX_RANGE:
        raise ValueError("invalid bounded history range or limit")
    return start, end, limit


def _cursor(resource: str, start: int, end: int, key: tuple[Any, Any]) -> str:
    raw = json.dumps({"v": 1, "resource": resource, "start": start, "end": end,
                      "last": [key[0], key[1]]}, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _read_cursor(value: str | None, resource: str, start: int, end: int) -> tuple[Any, Any] | None:
    if not value:
        return None
    try:
        if len(value) > 2048:
            raise ValueError
        padded = value + "=" * (-len(value) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(data,dict) or data.get("v") != 1 or data.get("resource") != resource or data.get("start") != start or data.get("end") != end:
            raise ValueError
        last = data["last"]
        if (not isinstance(last, list) or len(last) != 2
                or not isinstance(last[0], (int, float, str)) or isinstance(last[0], bool)
                or not isinstance(last[1], str)
                or (resource == "weights" and not isinstance(last[0],str))
                or (resource != "weights" and (type(last[0]) is not int))):
            raise ValueError
        return last[0], last[1]
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError, binascii.Error):
        raise ValueError("invalid cursor")


def _item_key(item: dict[str, Any]) -> tuple[Any, Any]:
    stamp = item.get("ts", item.get("start", item.get("observed_at", item.get("date", item.get("day", "")))))
    if isinstance(stamp, str) and stamp.isdigit():
        stamp = int(stamp)
    ident = item.get("id", item.get("source", ""))
    return stamp, str(ident)


def _stamp_in_range(item: dict[str, Any], start: int, end: int, zone=timezone.utc) -> bool:
    stamp = item.get("ts", item.get("start", item.get("observed_at")))
    date_value = item.get("date", item.get("day"))
    if stamp is None and date_value:
        try:
            stamp = datetime.combine(date.fromisoformat(str(date_value)), datetime.min.time(), zone).timestamp()
        except ValueError:
            return False
    return isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and start <= float(stamp) < end


def _db_history(resource: str, start: int, end: int) -> list[dict[str, Any]] | None:
    if fitness is None:
        return None
    with fitness.connect() as db:
        if resource == "minutes":
            return [dict(row) for row in db.execute(
                "SELECT ts,hr,steps,active FROM minutes WHERE ts>=? AND ts<? ORDER BY ts", (start, end))]
        if resource == "workouts":
            return [row for row in workout_edits.effective_rows(db)
                    if _stamp_in_range(row, start, end, fitness.TZ)]
        if resource == "sleep":
            return [dict(row) for row in db.execute(
                "SELECT id,start,seconds,kind FROM sleep_sessions WHERE start>=? AND start<? ORDER BY start", (start, end))]
        if resource == "oxygen":
            return [dict(row) for row in db.execute(
                "SELECT ts,percent,quality,source FROM oxygen_samples WHERE ts>=? AND ts<? ORDER BY ts", (start, end))]
        if resource == "weights":
            rows = [dict(row) for row in db.execute("SELECT day,kg,source FROM weights ORDER BY day")]
            return [row for row in rows if _stamp_in_range(row, start, end, fitness.TZ)]
        if resource == "hrv-sessions":
            items = []
            for row in db.execute("SELECT id,ts,payload FROM hrv_sessions WHERE ts>=? AND ts<? ORDER BY ts", (start, end)):
                payload = json.loads(row["payload"])
                item = {"id": row["id"], "ts": row["ts"]}
                for key in ("context", "collector_version", "count", "duration_ms", "firmware"):
                    if key in payload:
                        item[key] = payload[key]
                items.append(item)
            return items
    return []


def _db_raw(session_id: str) -> dict[str, Any] | list[Any] | None:
    if fitness is None:
        return None
    with fitness.connect() as db:
        row = db.execute("SELECT payload FROM hrv_sessions WHERE id=?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else None


def _public_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"value": item}
    forbidden = {"payload", "raw", "raw_payload", "ppi_intervals", "rr_intervals"}
    return {key: value for key, value in item.items() if key not in forbidden}


def _summary_metric(value: Any, unit: str | None = None, *, status: str | None = None,
                    estimated: bool = False, observed_at: Any = None) -> dict[str, Any] | None:
    if value is None or isinstance(value,bool) or not isinstance(value,(int,float,str)):
        return None
    if isinstance(value,(int,float)) and not math.isfinite(value): return None
    if isinstance(value,str) and len(value)>255: return None
    result = {"value": value, "unit": unit, "status": status or "observed",
              "estimated": bool(estimated)}
    if observed_at is not None:
        result["observed_at"] = observed_at
    return result


def _metrics(summary: dict[str, Any]) -> dict[str, Any]:
    stock = summary.get("stock_estimates") or {}
    readiness = (summary.get("recovery") or {}).get("readiness") or stock.get("readiness") or {}
    pulse = stock.get("pulse") or {}
    latest_pulse = pulse.get("latest") if isinstance(pulse.get("latest"), dict) else None
    strain = stock.get("strain") or {}
    sleep = (summary.get("recovery") or {}).get("sleep") or {}
    oxygen = summary.get("oxygen") or {}
    latest_o2 = oxygen.get("latest") or {}
    weight = (summary.get("weight") or {}).get("latest") or {}
    training = summary.get("training") or {}
    latest_training = training.get("latest") or {}
    hrv = summary.get("hrv") or {}
    diagnostic = hrv.get("diagnostic") or {}
    metrics = {
        "readiness": _summary_metric(readiness.get("score"), "score", status=readiness.get("status"), estimated=True,
                                      observed_at=readiness.get("observed_at", readiness.get("measured_at"))),
        "sleep_score": _summary_metric(sleep.get("score"), "score", status=sleep.get("status"), estimated=True, observed_at=sleep.get("night")),
        "sleep_hours": _summary_metric(float(sleep["sleep_s"]) / 3600 if isinstance(sleep.get("sleep_s"), (int, float)) else None, "h", status=sleep.get("status")),
        "overnight_pulse": _summary_metric(latest_pulse.get("pulse") if latest_pulse else None, "bpm", status=pulse.get("status"), estimated=True, observed_at=latest_pulse.get("observed_at") if latest_pulse else None),
        "overnight_strain": _summary_metric(strain.get("score"), "score", status=strain.get("status"), estimated=True, observed_at=strain.get("measured_at")),
        "spo2": _summary_metric(latest_o2.get("percent"), "%", status=oxygen.get("status"), observed_at=latest_o2.get("ts")),
        "weight": _summary_metric(weight.get("kg"), "kg", observed_at=weight.get("date")),
        "steps": _summary_metric((summary.get("latest") or {}).get("status", {}).get("steps"), "steps", observed_at=(summary.get("latest") or {}).get("ts")),
        "watch_battery": _summary_metric((summary.get("latest") or {}).get("status", {}).get("battery_percent"), "%", observed_at=(summary.get("latest") or {}).get("ts")),
        "training_load": _summary_metric(latest_training.get("load7"), "load", status=latest_training.get("status")),
        "acute_load": _summary_metric(latest_training.get("acute"), "load", status=latest_training.get("status"), estimated=True),
        "chronic_load": _summary_metric(latest_training.get("chronic"), "load", status=latest_training.get("status"), estimated=True),
        "hrv_rmssd": None,  # Stock PPI is not validated beat-to-beat HRV.
        "breathing_rate": None,  # No validated respiratory estimate yet.
    }

    latest=summary.get('latest') or {}
    snapshot=latest.get('status') or {}
    snap_ts=latest.get('ts')
    for key,field,unit,estimated in (
        ('snapshot_active_seconds','active_seconds','s',False),
        ('snapshot_distance','distance_meters','m',True),
        ('snapshot_active_energy','active_kcal','kcal',True),
        ('snapshot_resting_energy','resting_kcal','kcal',True),
        ('snapshot_sleep_seconds','sleep_seconds','s',False),
        ('snapshot_restful_sleep_seconds','sleep_restful_seconds','s',False)):
        metrics[key]=_summary_metric(snapshot.get(field),unit,estimated=estimated,observed_at=snap_ts)
    observed=[r for r in summary.get('observations',[]) if isinstance(r.get('hr'),(int,float)) and 0<r['hr']<=300 and r.get('ts',0)<=summary.get('now',time.time())]
    latest_hr=max(observed,key=lambda r:r['ts']) if observed else {}
    metrics['heart_rate']=_summary_metric(latest_hr.get('hr'),'bpm',observed_at=latest_hr.get('ts'))
    metrics['sleep_restful_hours']=_summary_metric(sleep.get('restful_s')/3600 if sleep.get('restful_s') is not None else None,'h',observed_at=sleep.get('night'))
    metrics['sleep_target_hours']=_summary_metric(sleep.get('need_s')/3600 if sleep.get('need_s') is not None else None,'h',status='configured')
    metrics['sleep_regularity_sd']=_summary_metric(sleep.get('regularity_sd_min'),'min',estimated=True,observed_at=sleep.get('night'))
    metrics['training_balance']=_summary_metric(latest_training.get('form'),'load',status=latest_training.get('status'),estimated=True)
    metrics['training_baseline_days']=_summary_metric(latest_training.get('baseline_days'),'d',status=latest_training.get('status'))
    metrics['training_known_days_7']=_summary_metric(latest_training.get('known_days7'),'d',status=latest_training.get('status'))
    fit=summary.get('fitness') or {}; energy=fit.get('energy') or {}; intensity=fit.get('intensity') or {}; vo2=fit.get('vo2max') or {}
    for key,value,unit in (
        ('bmr_estimate',energy.get('bmr_kcal'),'kcal'),('vo2max_estimate',vo2.get('value'),'mL/kg/min'),
        ('intensity_minutes_week',intensity.get('this_week'),'min'),('intensity_minutes_7d',intensity.get('last_7_days'),'min')):
        metrics[key]=_summary_metric(value,unit,status='estimated',estimated=True)
    composition=summary.get('composition') or {}
    people=composition.get('people') or []
    body=(people[0].get('metrics') or {}) if len(people)==1 else {}
    for key,unit in (('body_fat_pct','%'),('muscle_mass_kg','kg'),('bone_mass_kg','kg'),('body_water_pct','%'),('fat_mass_kg','kg'),('fat_free_mass_kg','kg'),('bmi',None)):
        item=body.get(key) or {}
        metrics[key]=_summary_metric(item.get('value'),unit,estimated=key in ('fat_mass_kg','fat_free_mass_kg'),observed_at=item.get('date'))
    metrics['weight_change_7d']=_summary_metric((summary.get('weight') or {}).get('change_7d_kg'),'kg',estimated=True,observed_at=weight.get('date'))
    metrics['weight_change_28d']=_summary_metric((summary.get('weight') or {}).get('change_28d_kg'),'kg',estimated=True,observed_at=weight.get('date'))
    metrics['oxygen_device_quality']=_summary_metric(latest_o2.get('quality'),None,status='raw_device_quality',observed_at=latest_o2.get('ts'))
    metrics['oxygen_samples_in_range']=_summary_metric(oxygen.get('sample_count'),'samples',status='stored_observations')
    collector=(summary.get('collection_health') or {}).get('collector') or {}
    metrics['night_slots_missed']=_summary_metric(collector.get('missed_slots'),'slots',status='schedule_evidence')
    for key,field in (('upload_age_seconds','sync_age_seconds'),('stored_reports','reports'),('stored_minutes_in_range','minute_records')):
        metrics[key]=_summary_metric(summary.get(field),'s' if key=='upload_age_seconds' else 'records',status='diagnostic')
    sessions=[w for w in summary.get('workouts',[]) if not w.get('ignored') and w.get('start',0)<=summary.get('now',time.time())]
    last=max(sessions,key=lambda w:w['start']) if sessions else {}
    metrics['last_workout_duration']=_summary_metric(last.get('seconds'),'s',observed_at=last.get('start'))
    metrics['last_workout_type']=_summary_metric(last.get('kind'),None,observed_at=last.get('start'))
    for metric in metrics.values():
        if metric is not None: metric.setdefault('source','pebble_health')
    return metrics


def _daily_metrics(now):
    """Observed canonical minute totals. Missing minutes are not filled with zero."""
    start=int(datetime.fromtimestamp(now,fitness.TZ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
    with fitness.connect() as db:
        rows=[dict(r) for r in db.execute('SELECT ts,hr,steps,active,payload FROM minutes WHERE ts>=? AND ts<=? ORDER BY ts',(start,now))]
    result={}
    for key,field,unit,estimated in (
        ('steps_today','steps','steps',False),('active_minutes_today','active','min',False),
        ('active_energy_today','active_kcal','kcal',True),('resting_energy_today','resting_kcal','kcal',True),
        ('distance_today','distance_m','m',True)):
        measured=[]
        for row in rows:
            payload=json.loads(row['payload']) if row['payload'] else {}
            value=row[field] if field in row else payload.get(field)
            if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<=value<=({'steps':10000,'active':1,'distance_m':100000}.get(field,10000)):
                measured.append((row['ts'],value))
        metric=_summary_metric(sum(value for _,value in measured) if measured else None,unit,status='observed_partial_day',estimated=estimated,observed_at=measured[-1][0] if measured else None)
        if metric is not None:
            metric.update(source='canonical_minutes',observed_minutes=len(measured),elapsed_minutes=max(0,(now-start)//60))
        result[key]=metric
    last=rows[-1] if rows else {}
    payload=json.loads(last['payload']) if last.get('payload') else {}
    for key,field in (('movement_intensity','intensity'),('ambient_light_intensity','light_intensity'),('watch_hr_zone','hr_zone')):
        result[key]=_summary_metric(payload.get(field),None,status='raw_watch_units',observed_at=last.get('ts'))
    return result


def factory(summary_provider):
    """Return a Flask blueprint using an injected summary/history provider."""
    bp = Blueprint("external_api", __name__, url_prefix="/api/v1")

    @bp.get("/summary")
    def summary_route():
        denied = _auth("summary:read")
        if denied is not None:
            return denied
        summary = summary_provider() if callable(summary_provider) else summary_provider.summary()
        now = summary.get("now", int(time.time())) if isinstance(summary, dict) else int(time.time())
        metrics=_metrics(summary)
        user=accounts.current()
        if fitness is not None and user is not None: metrics.update(_daily_metrics(now))
        # No token, password hash or administrator privileges leave the boundary.
        identity={key:user[key] for key in ('id','username','display_name')} if user else None
        return jsonify({"api_version": "1", "generated_at": now,
                        "account":identity,"timezone": str(fitness.TZ), "metrics": metrics})

    @bp.get("/<resource>")
    def history_route(resource):
        if resource not in RESOURCES:
            return jsonify(error="unknown resource"), 404
        denied = _auth("history:read")
        if denied is not None:
            return denied
        try:
            cursor_value = request.args.get("cursor")
            if cursor_value and len(cursor_value)>2048:
                return jsonify(error="invalid cursor"),400
            cursor_data = None
            if cursor_value and not request.args.get("start") and not request.args.get("end"):
                padded = cursor_value + "=" * (-len(cursor_value) % 4)
                cursor_data = json.loads(base64.urlsafe_b64decode(padded).decode())
                if not isinstance(cursor_data,dict): raise ValueError("invalid cursor")
                default_range = (int(cursor_data["start"]), int(cursor_data["end"]))
            else:
                default_range = None
            start, end, limit = _bounds(default_range)
            after = _read_cursor(cursor_value, resource, start, end)
        except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as error:
            return jsonify(error=str(error)), 400
        if resource == "workouts" and hasattr(summary_provider, "db"):
            import workout_edits
            source = workout_edits.effective_rows(summary_provider.db)
        elif hasattr(summary_provider, "history"):
            source = summary_provider.history(resource, start, end)
        elif (db_source := _db_history(resource, start, end)) is not None:
            source = db_source
        else:
            source = (summary_provider() if callable(summary_provider) else summary_provider).get(resource, [])
        zone = getattr(fitness, "TZ", timezone.utc)
        items = [_public_item(item) for item in source if isinstance(item, dict) and _stamp_in_range(item, start, end, zone)]
        items.sort(key=_item_key)
        if after is not None:
            items = [item for item in items if _item_key(item) > tuple(after)]
        page, rest = items[:limit], items[limit:]
        next_cursor = _cursor(resource, start, end, _item_key(page[-1])) if rest and page else None
        return jsonify({"api_version": "1", "generated_at": int(time.time()), "items": page,
                        "pagination": {"limit": limit, "next_cursor": next_cursor}})

    @bp.get("/hrv-sessions/<session_id>/raw")
    def raw_route(session_id):
        denied = _auth("raw:read")
        if denied is not None:
            return denied
        if hasattr(summary_provider, "raw_hrv"):
            payload = summary_provider.raw_hrv(session_id)
        else:
            payload = _db_raw(session_id)
        if payload is None:
            return jsonify(error="not found"), 404
        return jsonify({"api_version": "1", "generated_at": int(time.time()), "id": session_id, "raw": payload})

    return bp


# Production wiring uses this name; ``factory`` remains the explicit test/API
# name for callers that prefer it.
blueprint = factory
