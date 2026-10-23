import copy
import sqlite3
from datetime import date

import readiness_history as history
import recovery


def partial():
    return recovery.readiness([], {"score": 80, "sleep_s": 8 * 3600},
                              {"status": "ready", "date": "2026-10-21", "acute": 30, "chronic": 40},
                              date(2026, 10, 22))


def test_partial_coverage_and_identity():
    result = partial()
    assert result["components_count"] == 2
    assert result["available_count"] == 4
    assert result["effective_weight_coverage"] == .5
    assert result["provisional"] is True
    assert result["method_identity"]["input_keys"] == ["sleep", "training_load"]
    other = recovery.readiness([], {"score": 80, "sleep_s": 8 * 3600}, None, date(2026, 10, 22))
    assert other["comparability_key"] != result["comparability_key"]


def test_append_dedup_and_versions_preserve_existing_history():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE old_history(day TEXT, score INTEGER)")
    db.execute("INSERT INTO old_history VALUES ('2026-10-20', 50)")
    result = partial()
    result["notes"] = "private note must not persist"
    result["components"]["sleep"]["detail"] = "raw note must not persist"
    assert history.persist_daily(db, "2026-10-22", result, 1792660000)
    assert not history.persist_daily(db, "2026-10-22", result, 1792660001)
    changed = copy.deepcopy(result)
    changed["formula_version"] = "readiness-v3"
    assert history.persist_daily(db, "2026-10-22", changed, 1792660002)
    rows = history.read_history(db, 0, 1792700000)
    assert len(rows) == 2
    assert rows[0]["formula_version"] == "readiness-v3"
    assert "private note" not in str(rows)
    assert "raw note" not in str(rows)
    assert db.execute("SELECT * FROM old_history").fetchall() == [("2026-10-20", 50)]


def test_read_history_excludes_future_observation_and_day():
    db = sqlite3.connect(":memory:")
    history.persist_daily(db, "2026-10-22", partial(), 1792660000)
    history.persist_daily(db, "2026-10-22", dict(partial(), score=30), 1792800000)
    history.persist_daily(db, "2026-10-23", partial(), 1792660001)
    assert len(history.read_history(db, 0, 1792700000)) == 1
    assert history.read_history(db, 1792800000, 1792700000) == []


def test_completed_read_has_no_writer_lock_and_snapshots_are_immutable():
    import pytest
    db=sqlite3.connect(':memory:')
    history.persist_daily(db,'2026-10-22',partial(),1792660000)
    db.commit()
    statements=[]
    db.set_trace_callback(statements.append)
    history.read_history(db,0,1792700000)
    assert not db.in_transaction
    assert not any(s.lstrip().upper().startswith(('INSERT','CREATE','UPDATE','DELETE')) for s in statements)
    for query in ['UPDATE readiness_snapshots SET observed_at=1','DELETE FROM readiness_snapshots',
                  'INSERT OR REPLACE INTO readiness_snapshots SELECT * FROM readiness_snapshots']:
        with pytest.raises(sqlite3.IntegrityError):db.execute(query)
