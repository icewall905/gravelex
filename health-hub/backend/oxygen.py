"""Experimental optical SpO2 observations, retaining sampling times and raw quality.

No interpolation, diagnostic thresholds, readiness contribution or assumed sleep.
"""
import math
from datetime import datetime
from statistics import mean

NOTE = ('Experimental Pebble optical SpO2; sparse spot readings, not continuous monitoring. '
        'Missing samples are unknown. Raw device quality is retained without assuming a clinical interpretation. '
        'Not used to diagnose illness or calculate readiness, stress or training load.')


def ensure_schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS oxygen_samples(
      ts INTEGER NOT NULL, source TEXT NOT NULL, percent REAL NOT NULL,
      quality INTEGER, received INTEGER NOT NULL, PRIMARY KEY(ts,source))''')


def _number(value, lo, hi, label):
    if isinstance(value, bool) or not isinstance(value, (float,int)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{label} must be between {lo} and {hi}')
    return value


def ingest(db, payload, now):
    rows = payload.get('oxygen', [])
    if not isinstance(rows,list) or len(rows)>3000:
        raise ValueError('Invalid oxygen batch')
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError('Oxygen records must be objects')
        # Zero is the firmware sentinel for no measurement, not zero saturation.
        value = row.get('percent')
        if value is None or (not isinstance(value,bool) and value == 0):
            continue
        value = _number(value,1,100,'oxygen percent')
        ts = _number(row.get('ts'),946684800,now+300,'oxygen timestamp')
        if ts != int(ts):
            raise ValueError('Oxygen timestamp must be whole seconds')
        quality = row.get('quality')
        if quality is not None:
            quality = _number(quality,0,255,'oxygen quality')
            if quality != int(quality):
                raise ValueError('Oxygen quality must be an integer')
        # One device data-logging stream; re-exports must not inflate counts.
        db.execute('''INSERT INTO oxygen_samples(ts,source,percent,quality,received) VALUES(?,?,?,?,?)
          ON CONFLICT(ts,source) DO UPDATE SET percent=excluded.percent,
          quality=COALESCE(excluded.quality,oxygen_samples.quality),received=excluded.received''',
          (int(ts),'pebble-dls-v14',value,quality,now))


def summary(db,since,now,tz):
    rows=[dict(r) for r in db.execute('SELECT ts,percent,quality,source FROM oxygen_samples WHERE ts>=? AND ts<=? ORDER BY ts',(since,now))]
    latest=db.execute('SELECT ts,percent,quality,source FROM oxygen_samples WHERE ts<=? ORDER BY ts DESC LIMIT 1',(now,)).fetchone()
    groups={}
    for row in rows:
        day=datetime.fromtimestamp(row['ts'],tz).date().isoformat()
        groups.setdefault(day,[]).append(row['percent'])
    daily=[{'date':day,'count':len(values),'mean':round(mean(values),2),'min':min(values),'max':max(values)} for day,values in sorted(groups.items())]
    return {'status':'experimental' if latest else 'waiting_for_data','latest':dict(latest) if latest else None,
            'readings':rows,'daily':daily,'sample_count':len(rows),'note':NOTE,
            'latest_age_seconds':now-latest['ts'] if latest else None}


def ha_status(db,now,tz):
    start=int(datetime.fromtimestamp(now,tz).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
    row=db.execute('SELECT ts,percent,quality FROM oxygen_samples WHERE ts<=? ORDER BY ts DESC LIMIT 1',(now,)).fetchone()
    count=db.execute('SELECT count(*) FROM oxygen_samples WHERE ts>=? AND ts<=?',(start,now)).fetchone()[0]
    return {'spo2_pct':row['percent'] if row else None,'spo2_ts':row['ts'] if row else None,'spo2_samples_today':count,'spo2_quality':row['quality'] if row else None}
