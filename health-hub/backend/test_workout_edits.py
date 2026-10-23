import json
import sqlite3
from datetime import datetime, timezone

import pytest
import workout_edits as edits

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc).timestamp()
START = int(NOW-86400)


@pytest.fixture
def db():
    conn=sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE workouts(id TEXT PRIMARY KEY,start INTEGER,seconds INTEGER,kind TEXT,rpe REAL,source TEXT,ignored INTEGER)')
    conn.execute('CREATE TABLE day_confirmations(day TEXT PRIMARY KEY,status TEXT,confirmed_at INTEGER)')
    conn.execute('INSERT INTO workouts VALUES(?,?,?,?,?,?,?)',('a',START,3600,'run',6,'pebble',0))
    conn.execute("INSERT INTO day_confirmations VALUES('2026-10-22','complete',1)")
    conn.commit()
    return conn


def command(db,operation='edit',**values):
    base={'operation_id':'one','operation':operation,'id':'a','expected_revisions':{'a':0}}
    base.update(values)
    base.setdefault('expected_fingerprints', {row['id']:row['edit_fingerprint'] for row in edits.effective_rows(db)})
    return edits.apply_operation(db,base,NOW)


def test_read_without_schema_does_not_write(db):
    assert edits.effective_rows(db)[0]['edit_revision']==0
    assert not db.in_transaction
    assert not db.execute("SELECT name FROM sqlite_master WHERE name='workout_overlays'").fetchall()


def test_edit_survives_export_preserves_effort_and_is_audited(db):
    command(db,type='cycle',start=START+60,end=START+1860)
    db.execute('UPDATE workouts SET seconds=7200 WHERE id="a"')
    row=edits.effective_rows(db)[0]
    assert (row['kind'],row['seconds'],row['rpe'],row['ignored'])==('cycle',1800,6,0)
    assert db.execute('SELECT seconds FROM workouts').fetchone()[0]==7200
    before,after=db.execute('SELECT before_json,after_json FROM workout_edit_audit').fetchone()
    assert json.loads(before)[0]['kind']=='run'
    assert json.loads(after)[0]['kind']=='cycle'
    assert db.execute('SELECT count(*) FROM day_confirmations').fetchone()[0]==0


def test_replay_does_not_invalidate_new_confirmation(db):
    fingerprints={row['id']:row['edit_fingerprint'] for row in edits.effective_rows(db)}
    command(db,type='cycle',expected_fingerprints=fingerprints)
    db.execute("INSERT INTO day_confirmations VALUES('2026-10-22','complete',2)")
    assert command(db,type='cycle',expected_fingerprints=fingerprints)['replayed']
    assert db.execute('SELECT count(*) FROM day_confirmations').fetchone()[0]==1
    with pytest.raises(ValueError):command(db,type='run')


def test_split_preserves_effort_excludes_original_and_rejects_stale(db):
    result=command(db,'split',at=START+1200)
    active=[r for r in edits.effective_rows(db) if not r['ignored']]
    assert len(active)==2
    assert sum(r['seconds'] for r in active)==3600
    assert all(r['rpe']==6 for r in active)
    assert len(result['affected_ids'])==3
    with pytest.raises(edits.RevisionConflict):command(db,operation_id='two',type='cycle')


def test_merge_requires_explicit_keeper_and_connected_unique_ids(db):
    db.execute('INSERT INTO workouts VALUES(?,?,?,?,?,?,?)',('b',START+1800,3600,'walk',3,'manual',0))
    command(db,'merge',ids=['a','b'],keeper_id='a',expected_revisions={'a':0,'b':0})
    active=[r for r in edits.effective_rows(db) if not r['ignored']]
    assert len(active)==1 and active[0]['seconds']==5400 and active[0]['rpe']==6
    assert db.execute('SELECT count(*) FROM workouts').fetchone()[0]==2


@pytest.mark.parametrize('values',[
    {'start':True}, {'end':float('inf')}, {'end':START+30}, {'seconds':300},
    {'expected_revisions':{}}, {'expected_revisions':{'a':True}},
    {'operation':'split','at':START+30},
    {'operation':'merge','ids':['a','a'],'keeper_id':'a'},
])
def test_invalid_operation_is_atomic(db,values):
    edits.ensure_schema(db)
    with pytest.raises(ValueError):command(db,**values)
    assert db.execute('SELECT count(*) FROM workout_overlays').fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM workout_edit_audit').fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM day_confirmations').fetchone()[0]==1


def test_midnight_invalidates_all_touched_days_old_and_new(db):
    midnight=int(datetime(2026,10,23,tzinfo=timezone.utc).timestamp())
    command(db,start=midnight-600,end=midnight+600)
    days=json.loads(db.execute('SELECT result_json FROM workout_edit_audit').fetchone()[0])['invalidated_days']
    assert days==['2026-10-22','2026-10-23']


def test_gap_and_missing_merge_revision_rejected(db):
    db.execute('INSERT INTO workouts VALUES(?,?,?,?,?,?,?)',('b',START+7200,600,'walk',3,'manual',0))
    with pytest.raises(edits.RevisionConflict):
        command(db,'merge',ids=['a','b'],keeper_id='a')
    with pytest.raises(ValueError,match='gaps'):
        command(db,'merge',ids=['a','b'],keeper_id='a',expected_revisions={'a':0,'b':0})


def test_undo_restores_raw_state_with_new_revision_and_appends_audit(db):
    command(db,type='cycle')
    command(db,'undo',operation_id='two',target_operation_id='one',expected_revisions={'a':1})
    row=edits.effective_rows(db)[0]
    assert (row['kind'],row['seconds'],row['edit_revision'])==('run',3600,2)
    assert db.execute('SELECT count(*) FROM workout_edit_audit').fetchone()[0]==2
    result=edits.history(db,'a')
    assert len(result)==2 and result[0]['operation']=='undo'
    assert '_overlay' not in str(result)


def test_split_undo_excludes_children_and_restores_parent(db):
    command(db,'split',at=START+1200)
    revisions={row['id']:row['edit_revision'] for row in edits.effective_rows(db)}
    command(db,'undo',operation_id='two',target_operation_id='one',expected_revisions=revisions)
    active=[row for row in edits.effective_rows(db) if not row['ignored']]
    assert len(active)==1 and active[0]['id']=='a' and active[0]['seconds']==3600


def test_undo_rejects_changed_touched_record_even_with_current_revision(db):
    command(db,type='cycle')
    command(db,operation_id='two',rpe=8,expected_revisions={'a':1})
    with pytest.raises(edits.RevisionConflict,match='Cannot undo'):
        command(db,'undo',operation_id='three',target_operation_id='one',expected_revisions={'a':2})
    assert edits.effective_rows(db)[0]['rpe']==8


def test_merge_undo_restores_both_originals(db):
    db.execute('INSERT INTO workouts VALUES(?,?,?,?,?,?,?)',('b',START+1800,3600,'walk',3,'manual',0))
    command(db,'merge',ids=['a','b'],keeper_id='a',expected_revisions={'a':0,'b':0})
    command(db,'undo',operation_id='two',target_operation_id='one',expected_revisions={'a':1,'b':1})
    active=[row for row in edits.effective_rows(db) if not row['ignored']]
    assert [(row['id'],row['seconds'],row['rpe']) for row in active]==[('a',3600,6),('b',3600,3)]


def test_schema_bootstrap_concurrent_connections(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path=str(tmp_path/'edits.sqlite3')
    def initialize(_):
        conn=sqlite3.connect(path,timeout=5)
        try:
            edits.ensure_schema(conn)
            return conn.execute('SELECT version FROM workout_edit_schema').fetchall()
        finally:
            conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(initialize, range(2)))==[[(edits.SCHEMA_VERSION,)],[(edits.SCHEMA_VERSION,)]]


def test_local_midnight_policy_uses_configured_timezone(db,monkeypatch):
    from zoneinfo import ZoneInfo
    monkeypatch.setattr(edits,'TZ',ZoneInfo('Europe/Copenhagen'))
    # UTC 22:00 is local midnight before the October daylight-saving switch.
    midnight=int(datetime(2026,10,22,22,tzinfo=timezone.utc).timestamp())
    result=command(db,start=midnight-600,end=midnight+600)
    assert result['invalidated_days']==['2026-10-22','2026-10-23']


@pytest.mark.parametrize('mutation', [
    "UPDATE workout_edit_audit SET operation='changed'",
    'DELETE FROM workout_edit_audit',
    'INSERT OR REPLACE INTO workout_edit_audit SELECT * FROM workout_edit_audit',
    'REPLACE INTO workout_edit_audit SELECT * FROM workout_edit_audit',
])
def test_audit_is_immutable_including_replace(db,mutation):
    command(db,type='cycle')
    assert db.execute('PRAGMA recursive_triggers').fetchone()[0]==1
    with pytest.raises(sqlite3.IntegrityError,match='append-only'):
        db.execute(mutation)
    assert db.execute('SELECT operation FROM workout_edit_audit').fetchall()==[('edit',)]


def test_existing_schema_migrates_and_preserves_audit(db):
    command(db,type='cycle')
    db.execute('DELETE FROM workout_edit_schema')
    db.execute('INSERT INTO workout_edit_schema VALUES(1)')
    for name in ('update','delete','replace'):
        db.execute('DROP TRIGGER workout_audit_immutable_'+name)
    db.commit()
    assert not edits._schema_ready(db)
    # Existing overlays remain visible before migration is explicitly invoked.
    assert edits.effective_rows(db)[0]['kind']=='cycle'
    edits.ensure_schema(db)
    assert edits._schema_ready(db)
    assert db.execute('SELECT count(*) FROM workout_edit_audit').fetchone()[0]==1
    assert db.execute('SELECT version FROM workout_edit_schema ORDER BY version').fetchall()==[(1,),(2,)]


def test_completed_schema_and_reads_do_not_need_writer_lock(tmp_path):
    path=str(tmp_path/'writer.sqlite3')
    first=sqlite3.connect(path,timeout=.1)
    first.execute('CREATE TABLE workouts(id TEXT PRIMARY KEY,start INTEGER,seconds INTEGER)')
    first.commit()
    edits.ensure_schema(first)
    second=sqlite3.connect(path,timeout=.1)
    try:
        first.execute('BEGIN IMMEDIATE')
        edits.ensure_schema(second)
        assert not second.in_transaction
        assert edits.effective_rows(second)==[]
        assert edits.history(second,'missing')==[]
    finally:
        first.rollback()
        first.close()
        second.close()


def test_existing_schema_migration_concurrent_connections(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path=str(tmp_path/'existing.sqlite3')
    conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE workout_edit_schema(version INTEGER PRIMARY KEY)')
    conn.execute('INSERT INTO workout_edit_schema VALUES(1)')
    conn.execute('CREATE TABLE workout_overlays(id TEXT PRIMARY KEY,fields_json TEXT,revision INTEGER,created INTEGER)')
    conn.execute('CREATE TABLE workout_edit_audit(operation_id TEXT PRIMARY KEY,operation TEXT,observed_at REAL,request_hash TEXT,before_json TEXT,after_json TEXT,result_json TEXT)')
    conn.execute("INSERT INTO workout_edit_audit VALUES('legacy','edit',1,'hash','[]','[]','{}')")
    conn.commit()
    conn.close()
    def migrate(_):
        connection=sqlite3.connect(path,timeout=5)
        try:
            edits.ensure_schema(connection)
            return edits._schema_ready(connection), connection.execute('SELECT operation_id FROM workout_edit_audit').fetchall()
        finally:
            connection.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(migrate,range(2)))==[(True,[('legacy',)]),(True,[('legacy',)])]


def test_operation_leaves_transaction_commit_to_caller(db):
    assert not db.in_transaction
    command(db,type='cycle')
    assert db.in_transaction
    db.rollback()
    assert edits.effective_rows(db)[0]['kind']=='run'
    assert db.execute('SELECT count(*) FROM workout_edit_audit').fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM day_confirmations').fetchone()[0]==1


def test_raw_reexport_race_rejected_even_at_revision_zero(db):
    fingerprint=edits.effective_rows(db)[0]['edit_fingerprint']
    db.execute('UPDATE workouts SET seconds=4200 WHERE id="a"')
    with pytest.raises(edits.ConflictError,match='source changed'):
        command(db,type='cycle',expected_fingerprints={'a':fingerprint})
    assert edits.effective_rows(db)[0]['seconds']==4200


def test_undo_rejects_raw_reexport_after_type_only_edit(db):
    command(db,type='cycle')
    db.execute('UPDATE workouts SET seconds=4200 WHERE id="a"')
    with pytest.raises(edits.ConflictError,match='Cannot undo'):
        command(db,'undo',operation_id='two',target_operation_id='one',expected_revisions={'a':1})


def test_overridden_duration_ignores_ineffective_raw_reexport(db):
    command(db,end=START+1800)
    fingerprint=edits.effective_rows(db)[0]['edit_fingerprint']
    db.execute('UPDATE workouts SET seconds=4200 WHERE id="a"')
    assert edits.effective_rows(db)[0]['edit_fingerprint']==fingerprint
    command(db,operation_id='two',type='cycle',expected_revisions={'a':1},expected_fingerprints={'a':fingerprint})


def test_missing_fingerprints_rejected(db):
    with pytest.raises(edits.ConflictError):
        edits.apply_operation(db,{'operation_id':'missing','operation':'edit','id':'a','type':'cycle','expected_revisions':{'a':0}},NOW)
