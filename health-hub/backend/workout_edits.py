"""Audited workout corrections over immutable imported identities.

Callers own the transaction commit and authorization. All analytics must consume
``effective_rows`` rather than mixing original sessions and derived children.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get('PEBBLE_TZ', 'UTC'))


class ConflictError(ValueError):
    pass


RevisionConflict = ConflictError


SCHEMA_VERSION = 2


def _tables_exist(db):
    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('workout_edit_schema','workout_overlays','workout_edit_audit')")}
    return len(names) == 3


def _schema_ready(db):
    if not _tables_exist(db):
        return False
    if not db.execute('SELECT 1 FROM workout_edit_schema WHERE version=?', (SCHEMA_VERSION,)).fetchone():
        return False
    triggers = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'workout_audit_immutable_%'")}
    return {'workout_audit_immutable_update', 'workout_audit_immutable_delete',
            'workout_audit_immutable_replace'} <= triggers


def ensure_schema(db):
    db.execute("PRAGMA recursive_triggers=ON")
    if _schema_ready(db):
        return
    owned = not db.in_transaction
    if owned:
        db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS workout_edit_schema(version INTEGER PRIMARY KEY)')
        db.execute('''CREATE TABLE IF NOT EXISTS workout_overlays(
            id TEXT PRIMARY KEY, fields_json TEXT NOT NULL, revision INTEGER NOT NULL,
            created INTEGER NOT NULL DEFAULT 0)''')
        db.execute('''CREATE TABLE IF NOT EXISTS workout_edit_audit(
            operation_id TEXT PRIMARY KEY, operation TEXT NOT NULL, observed_at REAL NOT NULL,
            request_hash TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
            result_json TEXT NOT NULL)''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS workout_audit_immutable_update
            BEFORE UPDATE ON workout_edit_audit BEGIN
            SELECT RAISE(ABORT, 'Workout audit is append-only'); END''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS workout_audit_immutable_delete
            BEFORE DELETE ON workout_edit_audit BEGIN
            SELECT RAISE(ABORT, 'Workout audit is append-only'); END''')
        db.execute('''CREATE TRIGGER IF NOT EXISTS workout_audit_immutable_replace
            BEFORE INSERT ON workout_edit_audit
            WHEN EXISTS(SELECT 1 FROM workout_edit_audit WHERE operation_id=NEW.operation_id)
            BEGIN SELECT RAISE(ABORT, 'Workout audit is append-only'); END''')
        db.execute('INSERT OR IGNORE INTO workout_edit_schema VALUES(?)', (SCHEMA_VERSION,))
        if owned:
            db.commit()
    except Exception:
        if owned:
            db.rollback()
        raise


def _rows(cursor):
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _fingerprint(row):
    facts = {key: row.get(key) for key in ('id', 'start', 'seconds', 'kind', 'rpe', 'source')}
    facts['ignored'] = bool(row.get('ignored', False))
    return hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _with_fingerprints(rows):
    for row in rows:
        row['edit_fingerprint'] = _fingerprint(row)
    return sorted(rows, key=lambda row: (row['start'], row['id']))


def effective_rows(db, rows=None):
    base = rows if rows is not None else _rows(db.execute('SELECT * FROM workouts'))
    result = {str(row['id']): dict(row, edit_revision=0) for row in base}
    if not _tables_exist(db):
        return _with_fingerprints(result.values())
    for ident, raw, revision, created in db.execute('SELECT id,fields_json,revision,created FROM workout_overlays'):
        if ident not in result and not created:
            continue
        result.setdefault(ident, {'id': ident})
        result[ident].update(json.loads(raw), edit_revision=revision)
    return _with_fingerprints(result.values())


def _number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'Invalid {label}')
    return value


def _interval(start, end, now):
    start = _number(start, 'start', 946684800, now + 300)
    end = _number(end, 'end', start + 60, min(start + 86400, now + 300))
    if int(start) != start or int(end) != end:
        raise ValueError('Interval timestamps must be whole seconds')
    return int(start), int(end)


def _days(row):
    first = datetime.fromtimestamp(row['start'], TZ).date()
    last = datetime.fromtimestamp(row['start'] + row['seconds'] - 1, TZ).date()
    return {(first + timedelta(days=i)).isoformat() for i in range((last-first).days+1)}


def apply_operation(db, data, observed_at=None):
    """Atomically edit/split/merge; never delete source rows or rewrite audit.

    Merge uses an explicit keeper's type, effort and ignored state, and requires
    connected intervals. Split retains effort/ignored on both children. A replay
    returns the original result and does not invalidate newly reviewed days.
    """
    if not isinstance(data, dict):
        raise ValueError('Operation must be an object')
    ident = data.get('operation_id')
    if not isinstance(ident, str) or not 1 <= len(ident) <= 100 or any(not (c.isalnum() or c in '-_') for c in ident):
        raise ValueError('A bounded alphanumeric operation_id is required')
    now = float(time.time() if observed_at is None else observed_at)
    _number(now, 'observed_at', 946684800, 4102444800)
    request = json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False)
    digest = hashlib.sha256(request.encode()).hexdigest()
    ensure_schema(db)
    if not db.in_transaction:
        db.execute('BEGIN')
    db.execute('SAVEPOINT workout_edit')
    try:
        old = db.execute('SELECT request_hash,result_json FROM workout_edit_audit WHERE operation_id=?', (ident,)).fetchone()
        if old:
            if old[0] != digest:
                raise ValueError('operation_id already used for a different operation')
            result = dict(json.loads(old[1]), replayed=True)
            db.execute('RELEASE workout_edit')
            return result
        rows = {row['id']: row for row in effective_rows(db)}
        operation = data.get('operation')
        target = None
        if operation == 'undo':
            target = db.execute('SELECT before_json,after_json FROM workout_edit_audit WHERE operation_id=?',
                                (str(data.get('target_operation_id', '')),)).fetchone()
            if not target:
                raise ValueError('Target operation not found')
            target_before, target_after = json.loads(target[0]), json.loads(target[1])
            ids = [row['id'] for row in target_after]
        else:
            ids = data.get('ids') if operation == 'merge' else [data.get('id')]
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids)):
            raise ValueError('Distinct workout IDs required')
        if any(i not in rows for i in ids):
            raise ValueError('Workout not found')
        expected = data.get('expected_revisions')
        if not isinstance(expected, dict):
            raise ValueError('expected_revisions must be an object')
        for key in ids:
            if key not in expected or isinstance(expected[key], bool) or not isinstance(expected[key], int) or expected[key] != rows[key]['edit_revision']:
                raise RevisionConflict('Workout changed; reload before editing')
        fingerprints = data.get('expected_fingerprints')
        if not isinstance(fingerprints, dict):
            raise ConflictError('Current workout fingerprints are required; reload before editing')
        for key in ids:
            if fingerprints.get(key) != rows[key]['edit_fingerprint']:
                raise ConflictError('Workout source changed; reload before editing')
        if target:
            for row in target_after:
                if (rows[row['id']]['edit_revision'] != row['edit_revision'] or
                        rows[row['id']]['edit_fingerprint'] != row.get('edit_fingerprint')):
                    raise RevisionConflict('Cannot undo: a touched workout changed after that operation')
        before = [dict(rows[i]) for i in ids]
        for row in before:
            saved = db.execute('SELECT fields_json,created FROM workout_overlays WHERE id=?', (row['id'],)).fetchone()
            row['_overlay'] = {'fields': json.loads(saved[0]), 'created': saved[1]} if saved else None
        changes = {}
        created = set()
        if operation == 'edit':
            row = dict(before[0])
            allowed = {'operation_id', 'operation', 'id', 'expected_revisions', 'expected_fingerprints', 'type', 'start', 'end', 'rpe', 'ignored'}
            if set(data)-allowed:
                raise ValueError('Unknown edit field')
            start = data.get('start', row['start'])
            end = data.get('end', row['start']+row['seconds'])
            start, end = _interval(start, end, now)
            fields = {}
            if 'start' in data or 'end' in data:
                fields.update(start=start, seconds=end-start)
            if 'type' in data:
                if not isinstance(data['type'], str) or not data['type'].strip() or len(data['type']) > 40:
                    raise ValueError('Activity type must be 1 to 40 characters')
                fields['kind'] = data['type'].strip()
            if 'rpe' in data:
                fields['rpe'] = None if data['rpe'] is None else _number(data['rpe'], 'rpe', 1, 10)
            if 'ignored' in data:
                if not isinstance(data['ignored'], bool):
                    raise ValueError('ignored must be true or false')
                fields['ignored'] = int(data['ignored'])
            if not fields:
                raise ValueError('No changes supplied')
            changes[ids[0]] = fields
        elif operation == 'split':
            row = before[0]
            _interval(row['start'], row['start']+row['seconds'], now)
            point = _number(data.get('at'), 'split point', row['start']+60, row['start']+row['seconds']-60)
            if point != int(point):
                raise ValueError('Split point must be a whole second')
            changes[ids[0]] = {'ignored': 1}
            for index, (start, end) in enumerate(((row['start'], int(point)), (int(point), row['start']+row['seconds']))):
                key = f'edit:{ident}:{index}'
                child = {k: row[k] for k in ('kind', 'rpe', 'source', 'ignored') if k in row}
                child.update(start=start, seconds=end-start, source='edited')
                changes[key] = child
                created.add(key)
        elif operation == 'undo':
            prior = {row['id']: row for row in target_before}
            for key in ids:
                if key not in prior:
                    # A split child did not exist before: retain it as an excluded
                    # auditable derived row instead of deleting its identity.
                    saved = db.execute('SELECT fields_json FROM workout_overlays WHERE id=?', (key,)).fetchone()
                    changes[key] = json.loads(saved[0]) if saved else {}
                    changes[key]['ignored'] = 1
                else:
                    old_overlay = prior[key].get('_overlay')
                    changes[key] = dict(old_overlay['fields']) if old_overlay else {}
        elif operation == 'merge':
            keeper = data.get('keeper_id')
            if len(ids) < 2 or keeper not in ids:
                raise ValueError('Merge requires at least two IDs and an explicit keeper_id')
            ordered = sorted(before, key=lambda row: row['start'])
            end = ordered[0]['start']+ordered[0]['seconds']
            for row in ordered[1:]:
                if row['start'] > end:
                    raise ValueError('Merge intervals must overlap or touch; gaps cannot create exercise time')
                end = max(end, row['start']+row['seconds'])
            start, end = _interval(ordered[0]['start'], end, now)
            changes = {key: {'ignored': 1} for key in ids if key != keeper}
            changes[keeper] = {'start': start, 'seconds': end-start}
        else:
            raise ValueError('Choose edit, split, merge or undo')
        if any(key in rows for key in created):
            raise ValueError('Generated workout ID already exists')
        after = []
        for key, fields in changes.items():
            previous = db.execute('SELECT fields_json,revision,created FROM workout_overlays WHERE id=?', (key,)).fetchone()
            combined = json.loads(previous[0]) if previous and operation != 'undo' else {}
            combined.update(fields)
            revision = (previous[1] if previous else 0)+1
            db.execute('''INSERT INTO workout_overlays VALUES(?,?,?,?) ON CONFLICT(id)
                DO UPDATE SET fields_json=excluded.fields_json,revision=excluded.revision''',
                (key, json.dumps(combined, sort_keys=True), revision, int(key in created)))
            if operation == 'undo' and key in {r['id'] for r in target_before}:
                source = _rows(db.execute('SELECT * FROM workouts WHERE id=?', (key,)))
                row = dict(source[0]) if source else dict(rows.get(key, {'id': key}))
            else:
                row = dict(rows.get(key, {'id': key}))
            row.update(combined, edit_revision=revision)
            row['edit_fingerprint'] = _fingerprint(row)
            after.append(row)
        days = sorted(set().union(*(_days(row) for row in before+after)))
        db.executemany('DELETE FROM day_confirmations WHERE day=?', [(day,) for day in days])
        result = {'operation_id': ident, 'operation': operation, 'affected_ids': sorted(changes),
                  'invalidated_days': days, 'replayed': False}
        db.execute('INSERT INTO workout_edit_audit VALUES(?,?,?,?,?,?,?)',
                   (ident, operation, now, digest, json.dumps(before, sort_keys=True),
                    json.dumps(after, sort_keys=True), json.dumps(result, sort_keys=True)))
        db.execute('RELEASE workout_edit')
        return result
    except Exception:
        db.execute('ROLLBACK TO workout_edit')
        db.execute('RELEASE workout_edit')
        raise


def history(db, ident, limit=20):
    """Bounded public-safe correction history, excluding internal overlay state."""
    if not _tables_exist(db):
        return []
    limit = max(1, min(100, int(limit)))
    out = []
    for operation_id, operation, observed_at, before, after in db.execute(
            '''SELECT operation_id,operation,observed_at,before_json,after_json FROM workout_edit_audit
            WHERE EXISTS(SELECT 1 FROM json_each(before_json) WHERE json_extract(value,'$.id')=?)
               OR EXISTS(SELECT 1 FROM json_each(after_json) WHERE json_extract(value,'$.id')=?)
            ORDER BY observed_at DESC,rowid DESC LIMIT ?''', (ident, ident, limit)):
        before, after = json.loads(before), json.loads(after)
        if not any(row['id'] == ident for row in before+after):
            continue
        out.append({'operation_id': operation_id, 'operation': operation, 'observed_at': observed_at,
                    'before': [{k:v for k,v in row.items() if k != '_overlay'} for row in before], 'after': after})
        if len(out) >= limit:
            break
    return out
