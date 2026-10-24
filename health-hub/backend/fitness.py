"""Durable, single-wearer Pebble records and transparent training-load models."""
import json
import hashlib
import secrets
import math
import os
import sqlite3
import time
import threading
import training
import hrv as hrv_analytics
import recovery as recovery_model
import weight as weight_model
import physiology
import oxygen
import collection_health
import provenance
import training_ledger
import readiness_history
import monitor_observations
import stock_estimates
import motion_quality
import workout_edits
import uuid
import accounts
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("PEBBLE_TZ", "UTC"))  # the wearer's local day boundaries
DB_PATH = os.environ.get("FITNESS_DB", "/data/fitness.sqlite3")

SLEEP_KINDS = ("sleep", "restful_sleep")


_schema_lock = threading.Lock()


def _schema_ready(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='provenance_migrations'").fetchone()
    return bool(exists and db.execute('SELECT 1 FROM provenance_migrations WHERE version=2').fetchone())


def connect():
    path = accounts.health_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        fd=os.open(path, os.O_RDWR|os.O_CREAT|os.O_EXCL, 0o600)
        os.close(fd)
    except FileExistsError:
        pass
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA recursive_triggers=ON')
    try:
        if _schema_ready(db):
            return db
        # Local threads serialize bootstrap; BEGIN IMMEDIATE also serializes
        # other worker processes. Never use executescript inside this transaction.
        with _schema_lock:
            if _schema_ready(db):
                return db
            deadline = time.monotonic() + 15
            while True:
                try:
                    db.execute('PRAGMA journal_mode=WAL')
                    break
                except sqlite3.OperationalError as error:
                    if 'locked' not in str(error).lower() or time.monotonic() >= deadline:
                        raise
                    time.sleep(0.05)
            db.execute('BEGIN IMMEDIATE')
            if not _schema_ready(db):
                statements = """
    CREATE TABLE IF NOT EXISTS reports(ts INTEGER, source TEXT, received INTEGER, payload TEXT,
      PRIMARY KEY(ts,source));
    CREATE TABLE IF NOT EXISTS minutes(ts INTEGER PRIMARY KEY, hr INTEGER, steps INTEGER,
      active INTEGER, payload TEXT);
    CREATE TABLE IF NOT EXISTS workouts(id TEXT PRIMARY KEY, start INTEGER, seconds INTEGER,
      kind TEXT, rpe REAL, source TEXT);
    CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS pairing_tokens(hash TEXT PRIMARY KEY, expires INTEGER);
    CREATE TABLE IF NOT EXISTS day_confirmations(day TEXT PRIMARY KEY,status TEXT,confirmed_at INTEGER);
    CREATE TABLE IF NOT EXISTS collector_reports(ts INTEGER PRIMARY KEY,received INTEGER,payload TEXT);
    CREATE TABLE IF NOT EXISTS hrv_sessions(id TEXT PRIMARY KEY, ts INTEGER, payload TEXT);
    CREATE TABLE IF NOT EXISTS briefings(id INTEGER PRIMARY KEY, created INTEGER, day TEXT, model TEXT, status TEXT, payload TEXT, error TEXT, seconds REAL);
    CREATE TABLE IF NOT EXISTS weights(day TEXT PRIMARY KEY, kg REAL, source TEXT);
    CREATE TABLE IF NOT EXISTS sleep_sessions(id TEXT PRIMARY KEY, start INTEGER, seconds INTEGER, kind TEXT);
    """
                for statement in statements.split(';'):
                    if statement.strip():
                        db.execute(statement)
                if 'ignored' not in {r[1] for r in db.execute('PRAGMA table_info(workouts)')}:
                    db.execute('ALTER TABLE workouts ADD COLUMN ignored INTEGER NOT NULL DEFAULT 0')
                if 'scope' not in {r[1] for r in db.execute('PRAGMA table_info(pairing_tokens)')}:
                    db.execute("ALTER TABLE pairing_tokens ADD COLUMN scope TEXT NOT NULL DEFAULT 'hrv'")
                oxygen.ensure_schema(db)
                provenance.ensure_schema(db)
                provenance.seed_legacy_minutes(db)
            db.commit()
        return db
    except Exception:
        db.rollback()
        db.close()
        raise


def number(value, low, high, name):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def current_activity(db, now):
    """Partial local-day totals from canonical minutes, never a stale snapshot."""
    start = int(datetime.fromtimestamp(now,TZ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
    rows = db.execute('SELECT ts,steps,active,payload FROM minutes WHERE ts>=? AND ts<=? ORDER BY ts',(start,now)).fetchall()
    result = {'status':'observed_partial_day', 'source':'canonical_minutes', 'ts':None,
              'observed_minutes':{}, 'observed_at':{}, 'elapsed_minutes':max(0,(now-start)//60)}
    for field,limit in (('steps',10000),('active',1),('distance_m',100000),('active_kcal',10000),('resting_kcal',10000)):
        measured=[]
        for row in rows:
            payload=json.loads(row['payload']) if row['payload'] else {}
            value=row[field] if field in ('steps','active') else payload.get(field)
            if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and 0<=value<=limit:
                measured.append((row['ts'],value))
        output = 'active_seconds' if field=='active' else 'distance_meters' if field=='distance_m' else field
        result[output]=sum(v for _,v in measured)*(60 if field=='active' else 1) if measured else None
        result['observed_minutes'][output]=len(measured)
        result['observed_at'][output]=measured[-1][0] if measured else None
    times=[t for t in result['observed_at'].values() if t is not None]
    result['ts']=max(times) if times else None
    return result


BATTERY_MAX_AGE_SECONDS = 6 * 3600


def watch_battery(db, now):
    """Resolve battery independently of health backfills and transport receipts."""
    best = None
    query = "SELECT ts,received,source,payload FROM reports WHERE json_type(payload,'$.watch_status')='object' OR json_type(payload,'$.status.battery_percent') IN ('integer','real')"
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ingest_observations'").fetchone():
        # reports has a (second, source) key: a later page can replace the first
        # page in the same second. Immutable raw batches preserve its battery.
        query += " UNION ALL SELECT measured_ts AS ts,received,source,payload FROM ingest_observations WHERE kind='health_batch' AND json_type(payload,'$.watch_status')='object'"
    for row in db.execute(query + ' ORDER BY ts DESC'):
        payload = json.loads(row['payload'])
        direct = payload.get('watch_status') if row['source'] == 'gravelex' else None
        if isinstance(direct, dict) and direct.get('source') == 'gravelex_ble':
            percent, observed = direct.get('battery_percent'), direct.get('observed_at')
            source, device = 'gravelex_ble', direct.get('device_id')
        elif row['source'] == 'watchapp':
            percent, observed = (payload.get('status') or {}).get('battery_percent'), row['ts']
            source, device = 'watchapp', None
        else:
            continue
        if (isinstance(percent, bool) or not isinstance(percent, (int,float)) or not math.isfinite(percent)
                or percent != int(percent) or not 0 <= percent <= 100
                or isinstance(observed, bool) or not isinstance(observed, (int,float))
                or not math.isfinite(observed) or not 946684800 <= observed <= min(now + 300, row['received'] + 300)):
            continue
        # Equal-time direct GATT observations take precedence over watch-app snapshots.
        rank = (observed, source == 'gravelex_ble')
        if best is None or rank > best[0]:
            best = (rank, {'last_percent': int(percent), 'observed_at': int(observed),
                           'received_at': row['received'], 'source': source, 'device_id': device})
    if best is None:
        return {'percent': None, 'status': 'not_collected', 'observed_at': None, 'source': None}
    result = best[1]
    result['age_seconds'] = max(0, now - result['observed_at'])
    result['status'] = 'observed' if result['age_seconds'] <= BATTERY_MAX_AGE_SECONDS else 'stale'
    result['percent'] = result['last_percent'] if result['status'] == 'observed' else None
    return result


def ingest(data):
    now = int(time.time())
    ts = int(number(data.get("ts", now), 946684800, now + 300, "timestamp"))
    source = str(data.get("source", "phone"))[:80]
    if 'watch_status' in data:
        status = data['watch_status']
        if source != 'gravelex' or not isinstance(status, dict) or status.get('source') != 'gravelex_ble':
            raise ValueError('Invalid watch battery source')
        percent = number(status.get('battery_percent'), 0, 100, 'Watch battery')
        observed = number(status.get('observed_at'), 946684800, now + 300, 'Battery observation timestamp')
        if percent != int(percent) or observed != int(observed):
            raise ValueError('Battery percentage and observation timestamp must be integers')
        if status.get('device_id') is not None and (not isinstance(status['device_id'], str) or not 1 <= len(status['device_id']) <= 128):
            raise ValueError('Invalid battery device identity')
    rows = data.get("records", [])
    sessions = data.get("sessions", [])
    if not isinstance(rows, list) or len(rows) > 3000 or not isinstance(sessions, list) or len(sessions) > 1000:
        raise ValueError("Invalid record batch")
    with connect() as db:
        provenance.record_observation(db, "health_batch", source, ts, now, data)
        oxygen.ingest(db, data, now)
        db.execute("INSERT OR REPLACE INTO reports VALUES(?,?,?,?)", (ts, source, now, json.dumps(data)))
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Minute records must be objects")
            t = int(number(row.get("ts"), 946684800, now + 300, "record timestamp"))
            previous = db.execute("SELECT * FROM minutes WHERE ts=?", (t,)).fetchone()
            incoming = dict(row)
            incoming['ts'] = t
            for key, low, high in (("hr", 1, 300), ("steps", 0, 10000), ("active", 0, 1)):
                value = row.get(key)
                if key == "hr" and not isinstance(value, bool) and value == 0:
                    value = None
                if value is not None:
                    value = number(value, low, high, key)
                    if value != int(value):
                        raise ValueError(f"{key} must be an integer")
                    value = int(value)
                incoming[key] = value
            provenance.record_minute(db, source, ts, now, incoming)
            payload, winners = provenance.reconcile_minute(db, t)
            provenance.record_revision(db, t, json.loads(previous['payload']) if previous else None,
                                       payload, winners, now)
            db.execute("""INSERT INTO minutes(ts,hr,steps,active,payload) VALUES(?,?,?,?,?)
              ON CONFLICT(ts) DO UPDATE SET hr=excluded.hr,steps=excluded.steps,
              active=excluded.active,payload=excluded.payload""",
              (t, payload['hr'], payload['steps'], payload['active'], json.dumps(payload)))
        for s in sessions:
            if not isinstance(s, dict):
                raise ValueError("Sessions must be objects")
            start = int(number(s.get("start"), 946684800, now + 300, "session start"))
            seconds = int(number(s.get("seconds"), 1, 172800, "session duration"))
            kind = str(s.get("type", "workout"))[:40]
            ident = f"pebble:{start}:{kind}"
            if kind in SLEEP_KINDS:
                db.execute("""INSERT INTO sleep_sessions(id,start,seconds,kind) VALUES(?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET seconds=excluded.seconds""", (ident, start, seconds, kind))
                continue
            before=next((row for row in workout_edits.effective_rows(db) if row['id']==ident),None)
            db.execute("""INSERT INTO workouts(id,start,seconds,kind,rpe,source) VALUES(?,?,?,?,NULL,'pebble')
              ON CONFLICT(id) DO UPDATE SET seconds=excluded.seconds""", (ident, start, seconds, kind))
            after=next(row for row in workout_edits.effective_rows(db) if row['id']==ident)
            keys=('start','seconds','kind','rpe','ignored')
            if before is None or any(before.get(key)!=after.get(key) for key in keys):
                invalidate_workout_days(db,[row for row in (before,after) if row is not None])
    return ts


def sleep_sessions(since=0):
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id,start,seconds,kind FROM sleep_sessions WHERE start>=? ORDER BY start", (int(since),))]


def profile(data=None):
    with connect() as db:
        values={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}
        if data is not None:
            if 'hr_max' in data:
                value=data['hr_max']
                values['hr_max']=int(number(value,100,240,'Maximum heart rate')) if value is not None else None
            if 'load_method' in data:
                if data['load_method'] not in ('hr','rpe'):raise ValueError('Choose HR or session effort')
                values['load_method']=data['load_method']
            for key,value in values.items():
                db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value)))
    return {'hr_max':values.get('hr_max'), 'load_method':values.get('load_method','hr')}


def invalidate_workout_days(db, rows):
    for row in rows:
        first=datetime.fromtimestamp(row['start'],TZ).date()
        last=datetime.fromtimestamp(row['start']+row['seconds']-1,TZ).date()
        for offset in range((last-first).days+1):
            db.execute('DELETE FROM day_confirmations WHERE day=?',(str(first+timedelta(days=offset)),))


def edit_workouts(data):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        return workout_edits.apply_operation(db,data,observed_at=int(time.time()))


def workout_edit_history(ident):
    with connect() as db:
        return workout_edits.history(db,ident)


def add_workout(data):
    if data.get('id'):
        # Existing sessions are corrected through audited overlays, never raw imports.
        values={key:data[key] for key in ('rpe','ignored') if key in data}
        if not values:raise ValueError('Choose effort or exclusion to change')
        edit_workouts(dict(values,id=data['id'],operation='edit',
            operation_id=data.get('operation_id'),expected_revisions=data.get('expected_revisions'),expected_fingerprints=data.get('expected_fingerprints')))
        return str(data['id'])
    now=int(time.time())
    rpe=float(number(data.get('rpe'),1,10,'Perceived effort'))
    start=int(number(data.get('start'),946684800,now+300,'Workout start'))
    seconds=int(number(data.get('seconds'),60,86400,'Duration'))
    operation_id=str(data.get('operation_id') or uuid.uuid4())
    if len(operation_id)>80:raise ValueError('Operation ID is too long')
    ident='manual:'+operation_id
    kind=str(data.get('type','workout')).strip()[:40] or 'workout'
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        existing=db.execute('SELECT * FROM workouts WHERE id=?',(ident,)).fetchone()
        if existing:
            if any(existing[key]!=value for key,value in [('start',start),('seconds',seconds),('rpe',rpe),('kind',kind)]):
                raise ValueError('Operation ID already used for another workout')
            return ident
        provenance.record_observation(db,'manual_workout','manual',start,now,{'id':ident,'start':start,'seconds':seconds,'kind':kind,'rpe':rpe})
        db.execute("INSERT INTO workouts(id,start,seconds,kind,rpe,source) VALUES(?,?,?,?,?,'manual')",(ident,start,seconds,kind,rpe))
        # New evidence requires another explicit review of the affected calendar dates.
        first=datetime.fromtimestamp(start,TZ).date();last=datetime.fromtimestamp(start+seconds-1,TZ).date()
        for ago in range((last-first).days+1):
            db.execute('DELETE FROM day_confirmations WHERE day=?',(str(first+timedelta(days=ago)),))
    return ident


def collector_ingest(data):
    now=int(time.time())
    ts=int(number(data.get('ts'),946684800,now+300,'Collector timestamp'))
    payload={'ts':ts,'received':now,'collector_version':int(number(data.get('collector_version'),0,99999,'Collector version')),
      'schedule_ok':int(number(data.get('schedule_ok'),0,8,'Scheduled slots')),
      'schedule_error':int(number(data.get('schedule_error'),-10000,0,'Scheduler error')),
      'next_wakeup':int(number(data.get('next_wakeup'),0,now+8*86400,'Next wakeup')),
      'nights_enabled':data.get('nights_enabled') is True}
    payload['firmware']=str(data.get('firmware','unknown'))[:32]
    payload['phase']=int(number(data.get('phase',1),1,4,'Collector phase'))
    payload['launch']='scheduled' if data.get('launch')=='scheduled' else 'manual'
    for key,lo,hi in [('schedule_ids',-10000,2147483647),('schedule_times',0,now+8*86400)]:
        values=data.get(key,[])
        if not isinstance(values,list) or len(values)>6:raise ValueError('Invalid scheduled slots')
        payload[key]=[int(number(v,lo,hi,'Scheduled slot')) for v in values]
    with connect() as db:
        provenance.record_observation(db, 'collector_status', 'hrv-watch', ts, now, data)
        db.execute('INSERT OR REPLACE INTO collector_reports VALUES(?,?,?)',(ts,now,json.dumps(payload)))
    return {'ok':True}


def hrv_ingest(data):
    now = int(time.time())
    ts = int(number(data.get("ts"), 946684800, now + 300, "HRV timestamp"))
    ppi = data.get("ppi", [])
    offsets = data.get("offsets_ms", [])
    if not isinstance(ppi, list) or not 1 <= len(ppi) <= 1000 or len(offsets) != len(ppi):
        raise ValueError("HRV requires paired interval values and event times")
    for p in ppi:
        number(p, 1, 65535, "PPI")
    previous = -1
    for offset in offsets:
        number(offset, 0, 600000, "Event offset")
        if offset < previous:
            raise ValueError("Event times must be ordered")
        previous = offset
    motion_total = number(data.get("motion_total", 0), 0, 4294967295, "motion")
    motion_samples = number(data.get("motion_samples",0), 0, 100000, "motion sample count")
    normalized_windows = None
    if 'motion_windows' in data:
        normalized_windows = motion_quality.validate_windows(data['motion_windows'], motion_total, motion_samples)
    # Raw diagnostic only: event cadence does not establish consecutive beats.
    payload = {"ppi": ppi, "offsets_ms": offsets, "duration_ms": offsets[-1],
               "count": len(ppi), "context": "scheduled" if data.get("scheduled") is True else "manual", "motion_total": motion_total,
               "motion_samples": motion_samples,
               "validated": False, "rmssd": None}
    payload['firmware']=str(data.get('firmware','unknown'))[:32]
    payload['capacity_limited']=data.get('capacity_limited') is True
    for key in ('hrv_events','zero_ppi_events','hr_events','hr_sum','hr_valid'):
        payload[key]=int(number(data.get(key,0),0,1000000,'Sensor counter'))
    payload['mean_reported_hr']=round(payload['hr_sum']/payload['hr_valid'],2) if payload['hr_valid'] else None
    for key in ('collector_version','accel_callbacks','vibration_samples'):
        payload[key]=int(number(data.get(key,0),0,100000,'Collector '+key))
    payload['accel_rate_result']=int(number(data.get('accel_rate_result',0),-10000,10000,'Acceleration status'))
    if normalized_windows is not None:
        payload['motion_windows'] = normalized_windows
    payload['motion_source']='raw_accelerometer' if data.get('motion_source')=='raw_accelerometer' else 'processed_accelerometer'
    payload['vibration_status']='unknown' if payload['motion_source']=='raw_accelerometer' else 'flagged_samples_excluded'
    if payload['vibration_status']=='unknown':payload['vibration_samples']=None
    # All newly ingested watch PPI is delivered through the public callback;
    # without a source tag its beat continuity is unknown.  Keep the original
    # upload in the provenance journal, and only normalize the derived session
    # projection.  Existing rows are never rewritten.
    stream = data.get('stream_semantics')
    payload['stream_semantics'] = stream if stream in ('latest_ppi_updates', 'batched_ppi_unverified') else 'batched_ppi_unverified'
    with connect() as db:
        provenance.record_observation(db, "hrv_capture", "hrv-watch", ts, now, data)
        db.execute("INSERT OR REPLACE INTO hrv_sessions VALUES(?,?,?)", (f"ppi:{ts}", ts, json.dumps(payload)))
        # A saved physiological upload is authoritative evidence of a completed
        # collection. Link only launch metadata from that same measurement window.
        preceding=db.execute('SELECT payload FROM collector_reports WHERE ts BETWEEN ? AND ? ORDER BY ts DESC LIMIT 1',(ts-300,ts+5)).fetchone()
        outcome=json.loads(preceding['payload']) if preceding else {}
        outcome.update({'ts':min(now,ts+int(offsets[-1]/1000)),'received':now,'phase':3,
            'measurement_ts':ts,'collector_version':payload['collector_version'],
            'launch':payload['context'],'evidence':'measurement_saved'})
        db.execute('INSERT OR REPLACE INTO collector_reports VALUES(?,?,?)',(outcome['ts'],now,json.dumps(outcome)))
    return payload


def summary(days=42):
    now = int(time.time())
    days = max(7, min(int(days), 365))
    start_day = datetime.fromtimestamp(now, TZ).date() - timedelta(days=days - 1)
    since = int(datetime.combine(start_day, datetime.min.time(), TZ).timestamp())
    with connect() as db:
        latest = db.execute("SELECT * FROM reports WHERE source NOT IN ('phone-history','watch-history','gravelex') ORDER BY ts DESC LIMIT 1").fetchone()
        activity = current_activity(db, now)
        battery = watch_battery(db, now)
        receipt = db.execute("SELECT MAX(received) FROM reports").fetchone()[0]
        minutes = [dict(r) for r in db.execute("SELECT * FROM minutes WHERE ts>=? ORDER BY ts", (since,))]
        workouts = workout_edits.effective_rows(db)
        training_minutes = {}
        for workout in workouts:
            for row in db.execute("SELECT * FROM minutes WHERE ts>=? AND ts<?", (workout["start"],workout["start"]+workout["seconds"])):
                training_minutes[row["ts"]] = dict(row)
        confirmations={r['day']:r['status'] for r in db.execute('SELECT * FROM day_confirmations')}
        hrv_rows=[{'ts':r['ts'],'payload':json.loads(r['payload'])} for r in db.execute('SELECT ts,payload FROM hrv_sessions ORDER BY ts')]
        observed=[{'ts':r['ts'],'hr':r['hr'],'steps':r['steps']} for r in minutes]
        # Snapshots remain sparse observations, never workout HR coverage.
        for report in db.execute("SELECT ts,payload FROM reports WHERE source NOT IN ('phone-history','watch-history','gravelex') AND ts>=? ORDER BY ts",(since,)):
            raw=json.loads(report['payload']);status=raw.get('status',{})
            pulse=status.get('heart_rate_bpm') or (raw.get('heart_rate') or {}).get('bpm')
            if pulse:observed.append({'ts':report['ts'],'hr':pulse,'steps':None,'snapshot':True})
        collector_history=[json.loads(r['payload']) for r in db.execute('SELECT payload FROM collector_reports ORDER BY ts DESC LIMIT 12')]
        # Optional provisional-baseline spread imported from another device
        # (see research/seed_baseline.py); never raw history.
        seed_row=db.execute("SELECT value FROM settings WHERE key='baseline_seed'").fetchone()
        seed=json.loads(seed_row['value']) if seed_row else None
        if accounts.legacy_context():
            weight_model.sync(db, now)
        weight=weight_model.history(db, datetime.fromtimestamp(now,TZ).date())
        blood_oxygen=oxygen.summary(db,since,now,TZ)
        import briefing as briefing_model  # deferred: briefing imports this module
        brief=briefing_model.latest(db)
        body_row=db.execute("SELECT value FROM settings WHERE key='body_profile'").fetchone()
        fit_minutes=[(r[0],r[1],r[2]) for r in db.execute('SELECT ts,hr,steps FROM minutes WHERE ts>=? ORDER BY ts',(now-35*86400,))]
        active_today={}
        for r in db.execute("""SELECT ts,json_extract(payload,'$.status.active_kcal') k FROM reports WHERE source='watchapp' AND ts>=?""",(now-2*86400,)):
            if r['k'] is not None:
                d=datetime.fromtimestamp(r['ts'],TZ).date().isoformat()
                active_today[d]=max(active_today.get(d,0),int(r['k']))
        sleep_rows=[dict(r) for r in db.execute('SELECT start,seconds,kind FROM sleep_sessions WHERE start>=? ORDER BY start',(now-70*86400,))]
        # Hourly snapshots carry the watch's running sleep total for the current
        # local day; its daily maximum is the previous night's sleep.
        snapshot_sleep={}
        for r in db.execute("""SELECT ts,json_extract(payload,'$.status.sleep_seconds') s,json_extract(payload,'$.status.sleep_restful_seconds') rs
            FROM reports WHERE source='watchapp' AND ts>=?""",(now-70*86400,)):
            if r['s']:
                d=datetime.fromtimestamp(r['ts'],TZ).date().isoformat()
                if r['s']>snapshot_sleep.get(d,(0,0))[0]:snapshot_sleep[d]=(int(r['s']),int(r['rs'] or 0))
        collector=db.execute('SELECT payload FROM collector_reports ORDER BY ts DESC LIMIT 1').fetchone()
        hrv = db.execute("SELECT ts,payload FROM hrv_sessions ORDER BY ts DESC LIMIT 1").fetchone()
        count = db.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        collection = collection_health.build(db, now, TZ)
        hrv_recent = []
        for row in db.execute("SELECT ts,payload FROM hrv_sessions ORDER BY ts DESC LIMIT 12"):
            payload=json.loads(row["payload"])
            hrv_recent.append({"ts":row["ts"], "count":payload["count"], "duration_ms":payload["duration_ms"],
                "context":payload.get("context","manual"), "validated":False})
    config = profile()
    day_list=[str(start_day+timedelta(days=i)) for i in range(days)]
    earliest=min([start_day]+[datetime.fromtimestamp(w['start'],TZ).date() for w in workouts]+[datetime.fromisoformat(d).date() for d in confirmations])
    earliest=max(earliest,datetime.fromtimestamp(now,TZ).date()-timedelta(days=729))
    full_days=[str(earliest+timedelta(days=i)) for i in range((datetime.fromtimestamp(now,TZ).date()-earliest).days+1)]
    load=training.analyze(workouts,list(training_minutes.values()),full_days,config['hr_max'],config['load_method'],confirmations)
    ledger=training_ledger.build(load, confirmations, collection['daily'], datetime.fromtimestamp(now,TZ).date())
    full_history=load['history']
    finished=next((row for row in full_history if row['date']==ledger['baseline_end']),{})
    load['latest'].update(baseline_days=ledger['confirmed_consecutive_days'],status=ledger['status'],
                         baseline_end=ledger['baseline_end'],
                         acute=finished.get('acute'),chronic=finished.get('chronic'),form=finished.get('form'))
    load['history']=[r for r in load['history'] if r['date']>=str(start_day)]
    load['workouts']=[w for w in load['workouts'] if w['start']>=since]
    workouts=load['workouts'];history=load['history']
    recovery=hrv_analytics.analyze_history(hrv_rows, now=now)
    nightly=recovery_model.build([(r['ts'],hrv_analytics.analyze_session(r['payload'])) for r in hrv_rows if r['ts']>=now-70*86400],
                                 sleep_rows,snapshot_sleep,full_history,now,seed=seed)
    monitors=monitor_observations.build(hrv_rows,now,TZ)
    stock = stock_estimates.build(hrv_rows, [], nightly['sleep'],
        recovery_model.training_state(full_history, today=datetime.fromtimestamp(now,TZ).date()), now, TZ)
    # Stock pulse estimates form a new model/series. Strict HRV physiology and
    # its source gates remain unchanged and are retained separately.
    nightly['hrv_readiness'] = nightly['readiness']
    if os.environ.get('RECOVERY_MODE', 'stock_firmware') == 'stock_firmware':
        nightly['readiness'] = stock['readiness']
    else:
        stock['mode'] = 'diagnostics_only'
    with connect() as snapshot_db:
        readiness_history.persist_daily(snapshot_db, nightly['today'], nightly['readiness'], now)
        nightly['readiness_history']=readiness_history.read_history(snapshot_db, since, now)
    quality=hrv_analytics.analyze_session(json.loads(hrv['payload'])) if hrv else None
    last = json.loads(latest["payload"]) if latest else None
    return {"wearer": (accounts.current() or {}).get("display_name", os.environ.get("WEARER_NAME", "")), "now": now, "collector_history":collector_history, "collector":json.loads(collector["payload"]) if collector else None, "profile": config, "latest": last,
      "watch_battery": battery, "current_activity": activity,
      "last_received": receipt,
      "sync_age_seconds": max(0, now - receipt) if receipt is not None else None,
      "training_ledger": ledger, "collection_health": collection, "reports": count, "minute_records": len(minutes), "workouts": workouts, "history": history, "training": load,
      "observations": sorted(observed,key=lambda r:r["ts"])[-15000:], "confirmations": confirmations,
      "hrv": {"status": "diagnostic_only" if hrv else "not_collected", "ts": hrv["ts"] if hrv else None,
              "diagnostic": json.loads(hrv["payload"]) if hrv else None, "sessions": hrv_recent, "quality": quality, "analysis":recovery},
      "stock_estimates":stock, "monitor_observations":monitors, "oxygen": blood_oxygen, "stress": recovery["stress"], "recovery": nightly, "weight": weight, "briefing": brief,
      "fitness": physiology.fitness(json.loads(body_row['value']) if body_row else None,
                                    (weight or {}).get('latest',{}).get('trend_kg'), config.get('hr_max'),
                                    fit_minutes, active_today, TZ, datetime.fromtimestamp(now,TZ).date()),
      "model": {"hr": "Edwards-style zone minutes v1; at least 80% HR coverage", "rpe": "Session minutes × perceived effort (1–10)",
                "note": "Separate load scales. Unrecorded days are unknown; fitness/fatigue estimates need confirmed rest days and recording coverage."}}


def today():
    """Compact latest-recovery summary for the watch (the 'today' read scope)."""
    s = summary(7)
    rc = s["recovery"]
    ready, sleep, hs = rc["readiness"], rc["sleep"], rc["hrv_status"]
    night = rc["nights"][-1] if rc["nights"] and rc["nights"][-1]["night"] == rc["today"] else {}
    t = (s.get("training") or {}).get("latest") or {}
    status = (s.get("latest") or {}).get("status") or {}
    # ts is when the newest watch data arrived, so the watch's "updated ..."
    # reflects the data's age rather than the time of this request.
    data_ts = max([x for x in (s.get("last_received"), (s["hrv"] or {}).get("ts")) if x] or [None])
    return {"ts": data_ts, "readiness": ready.get("score"), "readiness_status": ready.get("status"), "readiness_method": ready.get("formula_version"),
            "readiness_estimated": ready.get("estimated", ready.get("provisional", True)),
            "sleep_score": sleep.get("score"),
            "sleep_min": round(sleep["sleep_s"] / 60) if sleep.get("sleep_s") is not None else None,
            "restful_min": round(sleep["restful_s"] / 60) if sleep.get("restful_s") is not None else None,
            "hrv_status": hs.get("status"), "hrv_ms": night.get("rmssd_ms"), "weekly_hrv_ms": hs.get("weekly_rmssd_ms"),
            "baseline_nights": hs.get("baseline_nights", 0), "rhr": night.get("resting_hr"),
            "breathing": night.get("breaths_per_min"), "load_acute": t.get("acute"), "load_chronic": t.get("chronic"),
            "steps": (s.get("current_activity") or {}).get("steps")}


def issue_hrv_token(scope="hrv", device_id=None):
    # 'today' is the only read scope: it can fetch the compact daily summary
    # for the watch, never history or raw data.
    if scope not in ("hrv","history","today"):raise ValueError("Unknown pairing scope")
    device_id = accounts.enrollment_device(device_id)
    token = secrets.token_urlsafe(32)
    expires = int(time.time()) + 30 * 86400
    with connect() as db:
        db.execute("DELETE FROM pairing_tokens WHERE expires < ?", (int(time.time()),))
        db.execute("INSERT INTO pairing_tokens(hash,expires,scope) VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), expires,scope))
    accounts.register_credential(token,"watch",device_id)
    return {"token": token, "expires": expires, "device_id": device_id}


def authorize_hrv(token, scope="hrv"):
    if not token or len(token) > 200:
        return False
    if not accounts.route_credential(token,"watch"):
        return False
    with connect() as db:
        return db.execute("SELECT 1 FROM pairing_tokens WHERE hash=? AND expires>? AND scope=?",
            (hashlib.sha256(token.encode()).hexdigest(), int(time.time()),scope)).fetchone() is not None


def refresh_hrv_token(token):
    with connect() as db:
        db.execute("UPDATE pairing_tokens SET expires=? WHERE hash=? AND expires>?", (
            int(time.time()) + 30 * 86400, hashlib.sha256(token.encode()).hexdigest(), int(time.time())))


def confirm_days_batch(data):
    if data.get('acknowledged') is not True:
        raise ValueError('Explicitly acknowledge that the selected dates were reviewed')
    today=datetime.now(TZ).date()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        workouts=workout_edits.effective_rows(db)
        minutes={}
        for workout in workouts:
            for row in db.execute('SELECT * FROM minutes WHERE ts>=? AND ts<?',(workout['start'],workout['start']+workout['seconds'])):
                minutes[row['ts']]=dict(row)
        settings={r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}
        analyzed=training.analyze(workouts,list(minutes.values()),[],settings.get('hr_max'),settings.get('load_method','hr'))
        items=training_ledger.validate_batch(data.get('days'),analyzed['workouts'],today)
        if any(datetime.fromisoformat(item['date']).date()<today-timedelta(days=730) for item in items):
            raise ValueError('Dates must be within the last 730 days')
        stamp=int(time.time())
        provenance.record_observation(db,'day_review','manual',stamp,stamp,{'days':items,'acknowledged':True})
        for item in items:
            if item['status']=='unknown':
                db.execute('DELETE FROM day_confirmations WHERE day=?',(item['date'],))
            else:
                db.execute('INSERT OR REPLACE INTO day_confirmations VALUES(?,?,?)',(item['date'],item['status'],stamp))
    return {'updated':len(items),'days':items}


def confirm_day(data):
    from datetime import date
    day=date.fromisoformat(str(data.get('date','')))
    if day>datetime.now(TZ).date() or day<datetime.now(TZ).date()-timedelta(days=730):raise ValueError('Day is outside the supported history')
    status=data.get('status')
    if status not in ('complete','rest','unknown'):raise ValueError('Choose complete, rest, or unknown')
    with connect() as db:
        if status=='rest':
            for row in workout_edits.effective_rows(db):
                if row.get('ignored'):continue
                if datetime.fromtimestamp(row['start'],TZ).date()==day:raise ValueError('This day has workouts. Confirm it complete or exclude duplicate sessions first.')
        if status=='unknown':db.execute('DELETE FROM day_confirmations WHERE day=?',(str(day),))
        else:db.execute('INSERT OR REPLACE INTO day_confirmations VALUES(?,?,?)',(str(day),status,int(time.time())))
    return {'date':str(day),'status':status}


def ha_history_status(db, now):
    """Forward recorded HR newer than the watch snapshot; never sum partial steps."""
    minute = db.execute('SELECT ts,hr FROM minutes WHERE hr BETWEEN 1 AND 300 AND ts<=? ORDER BY ts DESC LIMIT 1', (now,)).fetchone()
    if not minute:
        return {}
    snapshot = db.execute("SELECT ts FROM reports WHERE source NOT IN ('phone-history','watch-history','gravelex') AND json_extract(payload,'$.status.heart_rate_bpm') > 0 ORDER BY ts DESC LIMIT 1").fetchone()
    if snapshot and snapshot['ts'] >= minute['ts']:
        return {}
    return {'heart_rate_bpm': minute['hr'], 'heart_rate_ts': minute['ts'], 'heart_rate_source': 'recorded_history'}
