"""Collection evidence only: transport activity never establishes physiological freshness."""
import json
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo


def _payload(value):
    try:
        result = json.loads(value)
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def build(db, now, tz, days=7):
    """Return bounded, secret-free diagnostics without inferring wear or transfer state."""
    tz = ZoneInfo(tz) if isinstance(tz, str) else tz
    days = max(7, min(30, int(days)))
    today = datetime.fromtimestamp(now, tz).date()
    dates = [today - timedelta(days=i) for i in reversed(range(days))]
    since = int(datetime.combine(dates[0], time.min, tz).timestamp())
    rows = db.execute('SELECT ts,hr FROM minutes WHERE ts>=? AND ts<=? ORDER BY ts', (since, now)).fetchall()
    # UTC minute identities preserve both occurrences of an autumn repeated hour.
    groups = {}
    for ts, hr in rows:
        day = datetime.fromtimestamp(ts, tz).date().isoformat()
        any_rows, hr_rows = groups.setdefault(day, (set(), set()))
        any_rows.add(int(ts)//60)
        if isinstance(hr, (int, float)) and 0 < hr <= 300:
            hr_rows.add(int(ts)//60)
    daily = []
    for day in dates:
        start = int(datetime.combine(day, time.min, tz).timestamp())
        end = int(datetime.combine(day + timedelta(days=1), time.min, tz).timestamp())
        elapsed_end = min(end, now)
        expected = max(0, (elapsed_end-start)//60)
        any_rows, hr_rows = groups.get(day.isoformat(), (set(), set()))
        # Only elapsed full minutes enter the denominator or numerator.
        any_count = sum(start//60 <= v < elapsed_end//60 for v in any_rows)
        hr_count = sum(start//60 <= v < elapsed_end//60 for v in hr_rows)
        daily.append({'date':day.isoformat(), 'expected_minutes':expected,
                      'day_minutes':(end-start)//60, 'minute_buckets':any_count,
                      'hr_minutes':hr_count, 'hr_coverage_pct':round(100*hr_count/expected, 1) if expected else None})
    sources = [dict(zip(('source','reports','last_received','last_report_ts'), row)) for row in db.execute(
        'SELECT source,sum(received>=?),max(received),max(ts) FROM reports WHERE received<=? AND ts<=? GROUP BY source ORDER BY source', (since,now,now))]
    def latest(sql):
        row = db.execute(sql, (now,)).fetchone()
        return row[0] if row else None
    measured = {
        'heart_rate':latest('SELECT max(ts) FROM minutes WHERE hr>0 AND hr<=300 AND ts<=?'),
        'oxygen':latest('SELECT max(ts) FROM oxygen_samples WHERE percent>0 AND ts<=?'),
        'hrv':latest('SELECT max(ts) FROM hrv_sessions WHERE ts<=?'),
        'sleep_end':latest("SELECT max(start+seconds) FROM sleep_sessions WHERE seconds>0 AND kind IN ('sleep','restful_sleep') AND start+seconds<=?")}
    freshness = {key:{'measured_at':ts,'last_measured':ts,'age_seconds':now-ts if ts is not None else None} for key,ts in measured.items()}
    snapshot = db.execute("SELECT ts,received FROM reports WHERE ts<=? AND received<=? AND source NOT IN ('phone-history','watch-history','gravelex') ORDER BY ts DESC LIMIT 1", (now,now)).fetchone()
    collectors = db.execute('SELECT ts,received,payload FROM collector_reports WHERE ts>=? AND ts<=? AND received<=? ORDER BY ts DESC', (since,now,now)).fetchall()
    scheduled = [(ts,_payload(payload)) for ts,payload in db.execute('SELECT ts,payload FROM hrv_sessions WHERE ts>=? AND ts<=?', (since-300,now)) if _payload(payload).get('context')=='scheduled']
    advertisements = {}
    observations = []
    for ts, received, raw in reversed(collectors):
        payload = _payload(raw)
        times, ids = payload.get('schedule_times'), payload.get('schedule_ids')
        valid = None
        if isinstance(times,list) and isinstance(ids,list) and len(times)==len(ids):
            valid = {slot for slot, ident in zip(times,ids)
                     if isinstance(slot,int) and not isinstance(slot,bool) and slot>0
                     and isinstance(ident,int) and not isinstance(ident,bool) and ident>=0}
            for slot in valid:
                if since<=slot<=now:
                    advertisements.setdefault(slot, []).append(ts)
        observations.append((ts,payload.get('nights_enabled'),valid))
    schedule = sorted(advertisements) if advertisements else None
    slots = []
    used_measurements = set()
    for slot in schedule or []:
        matched = next((ts for ts,_ in scheduled if ts not in used_measurements and abs(ts-slot)<=300), None)
        if matched is not None:
            used_measurements.add(matched)
        before = [ts for ts in advertisements[slot] if ts<slot]
        advertised_at = min(before) if before else None
        ambiguous = advertised_at is None
        if advertised_at is not None:
            ambiguous = any(advertised_at<ts<slot and
                            (enabled is False or (valid is not None and slot not in valid))
                            for ts,enabled,valid in observations)
        status = ('saved' if matched is not None else 'unknown' if ambiguous
                  else 'missed' if now>slot+900 else 'pending')
        slots.append({'scheduled_ts':slot,'advertised_at':advertised_at,
                      'measurement_ts':matched,'status':status})
    tokens = []
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='pairing_tokens'").fetchone():
        tokens = [dict(zip(('scope','active','expired'), row)) for row in db.execute(
            'SELECT scope,sum(expires>?),sum(expires<=?) FROM pairing_tokens GROUP BY scope', (now,now))]
    receipts = [row['last_received'] for row in sources]
    collector_receipt = db.execute('SELECT max(received) FROM collector_reports WHERE received<=? AND ts<=?', (now,now)).fetchone()[0]
    if collector_receipt is not None:
        receipts.append(collector_receipt)
    oxygen_receipt = db.execute('SELECT max(received) FROM oxygen_samples WHERE received<=? AND ts<=?', (now,now)).fetchone()[0]
    if oxygen_receipt is not None:
        receipts.append(oxygen_receipt)
    received = max(receipts, default=None)
    return {'transport':{'last_received':received,'age_seconds':now-received if received is not None else None},
            'pairing_scopes':tokens, 'window_days':days,'since':since,'now':now,'daily':daily,'sources':sources,
            'measurements':freshness,'latest_snapshot':{'last_report_ts':snapshot[0],'last_received':snapshot[1]} if snapshot else None,
            'hr_gap_seconds':now-measured['heart_rate'] if measured['heart_rate'] is not None else None,
            'collector':{'last_report_ts':collectors[0][0] if collectors else None,
                         'last_received':max(row[1] for row in collectors) if collectors else None,
                         'last_saved_measurement':measured['hrv'], 'schedule_status':'historical_advertised' if schedule is not None else 'unknown',
                         'schedule_basis':'Persisted advertised slots; scheduler execution and cancellation are not directly observed.',
                         'expected_due':sum(s['status'] in ('saved','missed') and now>s['scheduled_ts']+900 for s in slots) if schedule is not None else None,
                         'stored':sum(s['status']=='saved' for s in slots) if schedule is not None else None,
                         'slots':slots,'missed_slots':sum(v['status']=='missed' for v in slots) if schedule is not None else None},
            'watch_phone_transfer':{'status':'unknown','reason':'Watch-to-phone transfer is not reported.'},
            'phone_backlog':{'status':'unknown','reason':'Phone queue depth is not reported.'},
            'note':'Coverage describes stored elapsed minute buckets, not wear time. Missing measurements and transport reports are separate evidence; no clinical freshness threshold is applied.'}
