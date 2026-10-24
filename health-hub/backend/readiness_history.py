"""Append-only, versioned readiness facts; never store source notes or raw records."""
from __future__ import annotations

import hashlib
import json
import math
import os
from zoneinfo import ZoneInfo
from datetime import date, datetime

SCHEMA_VERSION = 1


def ensure_schema(db):
    db.execute('PRAGMA recursive_triggers=ON')
    exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='readiness_history_schema'").fetchone()
    if exists and db.execute('SELECT 1 FROM readiness_history_schema WHERE version=?',(SCHEMA_VERSION,)).fetchone():
        return
    # Own additive migration registry: do not interfere with the fitness schema.
    db.execute("CREATE TABLE IF NOT EXISTS readiness_history_schema (version INTEGER PRIMARY KEY)")
    db.execute("""CREATE TABLE IF NOT EXISTS readiness_snapshots (
        id INTEGER PRIMARY KEY, day TEXT NOT NULL, observed_at REAL NOT NULL,
        formula_version TEXT NOT NULL, comparability_key TEXT NOT NULL,
        snapshot_hash TEXT NOT NULL, facts_json TEXT NOT NULL,
        UNIQUE(day, snapshot_hash))""")
    db.execute("CREATE INDEX IF NOT EXISTS readiness_snapshots_time ON readiness_snapshots(observed_at)")
    for action in ('UPDATE','DELETE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_readiness_{action.lower()} BEFORE {action} ON readiness_snapshots BEGIN SELECT RAISE(ABORT,'immutable readiness snapshot'); END")
    db.execute("INSERT OR IGNORE INTO readiness_history_schema(version) VALUES (?)", (SCHEMA_VERSION,))


def _facts(result):
    keys = ("score", "status", "components_count", "available_count", "total_components",
            "effective_weight_coverage", "provisional", "estimated", "confidence", "formula_version", "comparability_key")
    facts = {key: result[key] for key in keys if key in result}
    identity = result.get("method_identity") or {}
    series = identity.get("comparable_series") or {}
    facts["method_identity"] = {
        "formula_version": identity.get("formula_version"),
        "input_keys": sorted(k for k in identity.get("input_keys", [])
                             if k in ("hrv", "resting_hr", "sleep", "training_load")),
        "comparable_series": {k: series[k] for k in ("metric", "source", "algorithm_version", "firmware", "collector_version", "field") if k in series},
    }
    facts["components"] = {key: {k: component[k] for k in ("score", "provisional") if k in component}
                           for key, component in result.get("components", {}).items()
                           if key in ("hrv", "resting_hr", "sleep", "training_load")}
    return facts


def persist_daily(db, day, result, observed_at):
    """Append changed facts, deduplicate identical daily snapshots, leave commits to caller."""
    day = date.fromisoformat(str(day)).isoformat()
    observed_at = float(observed_at)
    if not math.isfinite(observed_at) or observed_at < 0:
        raise ValueError("Invalid observation time")
    ensure_schema(db)
    facts = _facts(result)
    payload = json.dumps(facts, sort_keys=True, separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    if db.execute('SELECT 1 FROM readiness_snapshots WHERE day=? AND snapshot_hash=?',(day,digest)).fetchone():
        return False
    cursor = db.execute("""INSERT OR IGNORE INTO readiness_snapshots
        (day, observed_at, formula_version, comparability_key, snapshot_hash, facts_json)
        VALUES (?, ?, ?, ?, ?, ?)""", (day, observed_at, str(facts.get("formula_version", "legacy_unknown")),
                                       str(facts.get("comparability_key", "legacy_unknown")), digest, payload))
    return cursor.rowcount == 1


def read_history(db, since, now):
    """At most 1000 snapshots in the requested observed-time interval; newest first."""
    since, now = float(since), float(now)
    if not math.isfinite(since) or not math.isfinite(now) or since > now:
        return []
    ensure_schema(db)
    rows = db.execute("""SELECT day, observed_at, formula_version, comparability_key,
        snapshot_hash, facts_json FROM readiness_snapshots
        WHERE observed_at >= ? AND observed_at <= ? AND day <= ?
        ORDER BY observed_at DESC, id DESC LIMIT 1000""", (since, now, datetime.fromtimestamp(now, ZoneInfo(os.environ.get("PEBBLE_TZ", "UTC"))).date().isoformat())).fetchall()
    return [dict(day=row[0], observed_at=row[1], formula_version=row[2],
                 comparability_key=row[3], snapshot_hash=row[4], readiness=json.loads(row[5])) for row in rows]
