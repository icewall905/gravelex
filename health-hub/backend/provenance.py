"""Immutable ingestion evidence and deterministic minute reconciliation.

Priority is a documented reconciliation policy, not a sensor-quality claim.
Ties use the first accepted report timestamp, then the persisted insertion
sequence. New corrections in the same report second win; replaying an old
observation never changes its sequence. Cross-source priority is arrival-independent. Equal-priority sources use their
lexical names before insertion sequence; this is not a quality claim. Callers own transaction boundaries; helpers never commit.
"""
import hashlib
import json
import time

ALGORITHM_VERSION = 'minute-source-v1'
SOURCE_PRIORITY = {'gravelex': 30, 'watch-history': 20, 'phone-history': 10,
                   'legacy-canonical': -100}
FIELDS = ('hr', 'steps', 'active')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def ensure_schema(db):
    db.execute("PRAGMA recursive_triggers=ON")
    # Completed migrations must not acquire a writer lock on every read.
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provenance_migrations'").fetchone()
    if exists and db.execute("SELECT 1 FROM provenance_migrations WHERE version=2").fetchone():
        return
    statements = [
        'CREATE TABLE IF NOT EXISTS provenance_migrations(version INTEGER PRIMARY KEY, applied INTEGER NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS ingest_observations(
           id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL,
           measured_ts INTEGER NOT NULL, received INTEGER, payload TEXT NOT NULL)''',
        '''CREATE TABLE IF NOT EXISTS minute_observations(
           id TEXT PRIMARY KEY REFERENCES ingest_observations(id), ts INTEGER NOT NULL,
           source TEXT NOT NULL, report_ts INTEGER NOT NULL, received INTEGER,
           hr INTEGER, steps INTEGER, active INTEGER, payload TEXT NOT NULL,
           algorithm_version TEXT NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS minute_observations_ts ON minute_observations(ts)',
        '''CREATE TABLE IF NOT EXISTS minute_revisions(
           id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, received INTEGER NOT NULL,
           previous_hash TEXT, canonical_hash TEXT NOT NULL, payload TEXT NOT NULL,
           winners TEXT NOT NULL, algorithm_version TEXT NOT NULL)''',
    ]
    for sql in statements:
        db.execute(sql)
    for table in ('ingest_observations', 'minute_observations', 'minute_revisions'):
        for action in ('UPDATE', 'DELETE'):
            db.execute(f'''CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()}
              BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable provenance'); END''')
    db.execute('INSERT OR IGNORE INTO provenance_migrations VALUES(1,?)', (int(time.time()),))


def record_observation(db, kind, source, measured_ts, received, payload):
    identity = digest({'kind': kind, 'source': source, 'measured_ts': measured_ts, 'payload': payload})
    db.execute('INSERT OR IGNORE INTO ingest_observations VALUES(?,?,?,?,?,?)',
               (identity, kind, source, measured_ts, received, canonical(payload)))
    return identity


def record_minute(db, source, report_ts, received, row):
    payload = dict(row)
    payload['ts'] = int(row['ts'])
    for key in FIELDS:
        value = payload.get(key)
        if key == 'hr' and value == 0 and not isinstance(value, bool):
            value = None
        payload[key] = value
    identity = record_observation(db, 'minute', source, payload['ts'], received, payload)
    db.execute('INSERT OR IGNORE INTO minute_observations VALUES(?,?,?,?,?,?,?,?,?,?)',
               (identity, payload['ts'], source, report_ts, received,
                payload['hr'], payload['steps'], payload['active'], canonical(payload), ALGORITHM_VERSION))
    return identity


def reconcile_minute(db, ts):
    rows = db.execute('SELECT id,source,report_ts,payload,rowid FROM minute_observations WHERE ts=?', (ts,)).fetchall()
    ranked = sorted(rows, key=lambda r: (SOURCE_PRIORITY.get(r[1], 0), r[2], r[1], r[4], r[0]), reverse=True)
    payload, winners = {'ts': ts}, {}
    for identity, source, report_ts, raw, sequence in ranked:
        for key, value in json.loads(raw).items():
            if key != 'ts' and value is not None and key not in winners:
                payload[key] = value
                winners[key] = identity
    for key in FIELDS:
        payload.setdefault(key, None)
    return payload, winners


def seed_legacy_minutes(db):
    if db.execute('SELECT 1 FROM provenance_migrations WHERE version=2').fetchone():
        return 0
    count = 0
    for ts, hr, steps, active, raw in db.execute('SELECT ts,hr,steps,active,payload FROM minutes').fetchall():
        payload = json.loads(raw) if raw else {}
        payload.update(ts=ts, hr=hr, steps=steps, active=active)
        record_minute(db, 'legacy-canonical', ts, None, payload)
        count += 1
    db.execute('INSERT INTO provenance_migrations VALUES(2,?)', (int(time.time()),))
    return count


def record_revision(db, ts, previous, payload, winners, received):
    if previous == payload:
        return False
    current_hash = digest(payload)
    db.execute('''INSERT INTO minute_revisions(ts,received,previous_hash,canonical_hash,payload,winners,algorithm_version)
                  VALUES(?,?,?,?,?,?,?)''',
               (ts, received, digest(previous) if previous is not None else None,
                current_hash, canonical(payload), canonical(winners), ALGORITHM_VERSION))
    return True


def rebuild_minutes(db):
    count = 0
    # No deletion: an empty observation store must never erase existing data.
    for (ts,) in db.execute('SELECT DISTINCT ts FROM minute_observations ORDER BY ts').fetchall():
        payload, winners = reconcile_minute(db, ts)
        old = db.execute('SELECT payload FROM minutes WHERE ts=?', (ts,)).fetchone()
        previous = json.loads(old[0]) if old else None
        record_revision(db, ts, previous, payload, winners, int(time.time()))
        db.execute('''INSERT INTO minutes(ts,hr,steps,active,payload) VALUES(?,?,?,?,?)
          ON CONFLICT(ts) DO UPDATE SET hr=excluded.hr,steps=excluded.steps,
          active=excluded.active,payload=excluded.payload''',
                   (ts, payload['hr'], payload['steps'], payload['active'], canonical(payload)))
        count += 1
    return count


def minute_details(db, ts, limit=50):
    """Bounded diagnostic projection: never expose raw batches or extra fields."""
    limit = max(1, min(50, int(limit)))
    stored = db.execute('SELECT hr,steps,active FROM minutes WHERE ts=?', (ts,)).fetchone()
    _, winners = reconcile_minute(db, ts)
    rows = db.execute('''SELECT id,source,report_ts,received,hr,steps,active,algorithm_version
                         FROM minute_observations WHERE ts=? ORDER BY received DESC,id LIMIT ?''', (ts, limit)).fetchall()
    keys = ('id', 'source', 'report_ts', 'received', 'hr', 'steps', 'active', 'algorithm_version')
    return {'ts': ts, 'canonical': dict(zip(FIELDS, stored)) if stored else None,
            'winners': {key: winners.get(key) for key in FIELDS},
            'observations': [dict(zip(keys, row)) for row in rows],
            'algorithm_version': ALGORITHM_VERSION,
            'source_policy': 'Self-declared compatibility priority, not authenticated sensor quality'}
