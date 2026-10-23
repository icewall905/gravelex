"""Auditable calendar confirmations; sensor coverage never implies rest."""
from datetime import date, datetime, timedelta
import math
import training


def _day(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError('date must be YYYY-MM-DD')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('date must be YYYY-MM-DD')
    return parsed


def _sessions(workouts, day):
    return [w for w in workouts if not w.get('ignored') and
            datetime.fromtimestamp(training._ts(w['start']), training.TZ).date() == day]


def _scoreable(w):
    load = w.get('load')
    return (not w.get('excluded') and not w.get('overlap') and
            isinstance(load, (int, float)) and not isinstance(load, bool) and
            math.isfinite(load) and load >= 0)


def validate_batch(items, workouts, today):
    """Validate all updates before a caller opens its write transaction.

    Returns normalized date/status objects. ``unknown`` means delete the stored
    confirmation. Workouts must be the current analyzed workout set, with the
    user's selected load method already applied. No partial writes occur here.
    """
    today = _day(today)
    if not isinstance(items, list) or not 1 <= len(items) <= 42:
        raise ValueError('batch must contain 1 to 42 dates')
    seen, result = set(), []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('each confirmation must be an object')
        d = _day(item.get('date'))
        if d >= today:
            raise ValueError('only finished days before today can be confirmed')
        if d in seen:
            raise ValueError('batch dates must be unique')
        seen.add(d)
        status = item.get('status')
        if status not in ('complete', 'rest', 'unknown'):
            raise ValueError('status must be complete, rest or unknown')
        sessions = _sessions(workouts, d)
        if status == 'rest' and sessions:
            raise ValueError(f'{d}: recorded sessions prevent a rest confirmation')
        if status == 'complete' and (not sessions or not all(_scoreable(w) for w in sessions)):
            raise ValueError(f'{d}: all active sessions need a valid selected-method load')
        result.append({'date': d.isoformat(), 'status': status})
    return result


def build(trainingresult, confirmations, collection_daily, today):
    """Explain the 42 finished-day window, preserving an open today's status."""
    today = _day(today)
    end = today - timedelta(days=1)
    history = {h['date']: h for h in trainingresult.get('history', [])}
    workouts = trainingresult.get('workouts', [])
    coverage = {r['date']: r for r in (collection_daily or [])}
    rows = []
    for offset in range(41, -1, -1):
        d = end - timedelta(days=offset)
        key = d.isoformat()
        h = history.get(key, {})
        sessions = _sessions(workouts, d)
        confirmation = (confirmations or {}).get(key)
        valid = bool(sessions) and all(_scoreable(w) for w in sessions)
        status = ('complete' if confirmation == 'complete' and valid else
                  'rest' if confirmation == 'rest' and not sessions else
                  'partial' if sessions else 'unknown')
        reasons = []
        if status not in ('complete', 'rest'):
            if confirmation is None:
                reasons.append('Day has not been explicitly confirmed')
            if confirmation == 'rest' and sessions:
                reasons.append('Rest confirmation conflicts with recorded sessions')
            if sessions and not valid:
                reasons.append('One or more sessions lack a valid selected-method load or overlap')
            if confirmation == 'complete' and not sessions:
                reasons.append('Complete confirmation has no active sessions')
        evidence = coverage.get(key, {})
        rows.append({'date': key, 'status': status, 'confirmation': confirmation,
                     'confirmed_load': (sum(w['load'] for w in sessions) if status == 'complete' else
                                        0.0 if status == 'rest' else None),
                     'recorded_hr_load': _sum_load(sessions, 'hr_load'),
                     'recorded_rpe_load': _sum_load(sessions, 'rpe_load'),
                     'workouts': sessions, 'blockers': reasons,
                     'hr_minutes': evidence.get('hr_minutes'),
                     'hr_coverage_pct': evidence.get('hr_coverage_pct'),
                     'acute': h.get('acute'), 'chronic': h.get('chronic'), 'form': h.get('form')})
    run = 0
    cursor = end
    # Count beyond the visible 42-day window when history supports it.
    while True:
        key = cursor.isoformat()
        h = history.get(key)
        if not h or not h.get('complete') or h.get('status') not in ('complete', 'rest'):
            break
        run += 1
        cursor -= timedelta(days=1)
    # The visible ledger is authoritative if persisted confirmations contradict history.
    visible_run = 0
    for row in reversed(rows):
        if row['status'] not in ('complete', 'rest'):
            break
        visible_run += 1
    run = max(visible_run, run) if visible_run == 42 else visible_run
    blockers = [{'date': r['date'], 'status': r['status'], 'reasons': r['blockers']}
                for r in rows if r['status'] not in ('complete', 'rest')]
    return {'as_of': today.isoformat(), 'baseline_end': end.isoformat(),
            'window_start': rows[0]['date'], 'required_days': 42,
            'confirmed_consecutive_days': run, 'confirmed_days': 42 - len(blockers),
            'missing_days': [r['date'] for r in rows if r['status'] == 'unknown'],
            'partial_days': [r['date'] for r in rows if r['status'] == 'partial'],
            'status': 'ready' if run >= 42 else 'warming', 'blockers': blockers,
            'days': rows, 'today': {'date': today.isoformat(), 'status': 'open'},
            'note': 'Baseline ends yesterday. HR coverage is evidence, not proof of rest or complete training.'}


def _sum_load(sessions, field):
    active = [w for w in sessions if not w.get('excluded') and not w.get('overlap')]
    values = [w.get(field) for w in active]
    if not values or len(active) != len(sessions) or any(
            not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0
            for v in values):
        return None
    return round(sum(values), 3)
