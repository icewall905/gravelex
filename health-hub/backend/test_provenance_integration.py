"""Ingestion and recovery keep immutable evidence in the same transaction."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import pytest
import fitness
import provenance


@pytest.fixture
def store(tmp_path,monkeypatch):
    path=tmp_path/'history.sqlite3'
    monkeypatch.setattr(fitness,'DB_PATH',str(path))
    return path,int(time.time())-120


def counts():
    with fitness.connect() as db:
        return [db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in
                ['ingest_observations','minute_observations','minute_revisions','reports','minutes']]


def test_replay_invalid_batch_and_original_sentinel_are_auditable(store):
    path,ts=store
    data={'source':'gravelex','ts':ts+60,'records':[{'ts':ts,'hr':0,'steps':2,'private_note':'never in projection'}]}
    fitness.ingest(data)
    before=counts()
    fitness.ingest(data)
    assert counts()==before
    with pytest.raises(ValueError):
        fitness.ingest({'source':'gravelex','records':[{'ts':ts+1,'hr':80},{'ts':ts+2,'hr':False}]})
    assert counts()==before
    with fitness.connect() as db:
        raw=json.loads(db.execute("SELECT payload FROM ingest_observations WHERE kind='health_batch'").fetchone()[0])
        assert raw['records'][0]['hr']==0
        detail=provenance.minute_details(db,ts)
        assert detail['canonical']['hr'] is None
        assert 'private_note' not in json.dumps(detail)


def test_canonical_repair_is_audited_and_workout_rpe_survives(store):
    path,ts=store
    fitness.ingest({'source':'gravelex','ts':ts+60,'records':[{'ts':ts,'hr':70,'steps':3}]})
    workout=fitness.add_workout({'start':ts-3600,'seconds':600,'rpe':6,'type':'run'})
    with fitness.connect() as db:
        before=db.execute('SELECT count(*) FROM minute_revisions').fetchone()[0]
        db.execute('UPDATE minutes SET hr=99,payload=? WHERE ts=?',(json.dumps({'ts':ts,'hr':99}),ts))
        provenance.rebuild_minutes(db)
        assert db.execute('SELECT hr FROM minutes WHERE ts=?',(ts,)).fetchone()[0]==70
        assert db.execute('SELECT rpe FROM workouts WHERE id=?',(workout,)).fetchone()[0]==6
        assert db.execute('SELECT count(*) FROM minute_revisions').fetchone()[0]==before+1
        provenance.rebuild_minutes(db)
        assert db.execute('SELECT count(*) FROM minute_revisions').fetchone()[0]==before+1


def test_completed_migration_does_not_write_again(store):
    with fitness.connect() as db:
        pass
    with sqlite3.connect(str(store[0])) as db:
        statements=[]
        db.set_trace_callback(statements.append)
        provenance.ensure_schema(db)
        provenance.seed_legacy_minutes(db)
        assert not any(x.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE')) for x in statements)


def test_cli_preview_never_writes_and_apply_requires_new_private_backup(store,tmp_path):
    path,ts=store
    fitness.ingest({'source':'gravelex','records':[{'ts':ts,'hr':70}]})
    with fitness.connect() as db:
        db.execute('UPDATE minutes SET hr=90,payload=?',(json.dumps({'ts':ts,'hr':90}),))
    script=Path(__file__).parents[1]/'scripts'/'rebuild-minutes.py'
    def command(*args):
        return subprocess.run([sys.executable,str(script),'--database',str(path),*args],capture_output=True,text=True,timeout=20)
    preview=command()
    assert preview.returncode==0,preview.stderr
    assert json.loads(preview.stdout)['changed'] is True
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT hr FROM minutes').fetchone()[0]==90
    assert command('--apply').returncode!=0
    backup=tmp_path/'private-backup.sqlite3'
    result=command('--apply','--backup',str(backup))
    assert result.returncode==0,result.stderr
    assert backup.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT hr FROM minutes').fetchone()[0]==70
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT hr FROM minutes').fetchone()[0]==90
    assert command('--apply','--backup',str(backup)).returncode!=0


def test_parallel_fresh_initialization_and_read_connections(store):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    barrier=threading.Barrier(6)
    def initialize(_):
        barrier.wait()
        with fitness.connect() as db:
            assert db.execute('SELECT count(*) FROM provenance_migrations').fetchone()[0]==2
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(initialize,range(6)))
    with fitness.connect() as db:
        assert not db.in_transaction
        assert db.execute('SELECT count(*) FROM minute_observations').fetchone()[0]==0


def test_independent_worker_processes_initialize_atomically(store):
    path,ts=store
    code='import sys;sys.path.insert(0,sys.argv[1]);import fitness;fitness.DB_PATH=sys.argv[2];db=fitness.connect();assert not db.in_transaction;db.close()'
    backend=str(Path(__file__).parent)
    workers=[subprocess.Popen([sys.executable,'-c',code,backend,str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(4)]
    for worker in workers:
        out,error=worker.communicate(timeout=30)
        assert worker.returncode==0,error


def test_protected_dashboard_projection_is_bounded_and_rejects_bad_timestamp(store, monkeypatch):
    import dashboard
    path,ts=store
    fitness.ingest({'source':'gravelex','records':[{'ts':ts,'hr':70,'private_extra':'do-not-return'}]})
    monkeypatch.setenv('PH_PASSWORD_HASH','configured')
    monkeypatch.setenv('PH_SESSION_SECRET','configured')
    client=dashboard.app.test_client()
    client.environ_base['HTTP_X_PH_REQUEST']='1'
    with client.session_transaction() as session: session['authenticated']=True
    result=client.get('/api/provenance/minute',query_string={'ts':ts})
    assert result.status_code==200
    data=result.get_json()
    assert data['canonical']['hr']==70
    assert data['winners']['hr']==data['observations'][0]['id']
    assert 'private_extra' not in result.get_data(as_text=True)
    for value in ['', 'invalid', '-1', str(int(time.time())+999)]:
        assert client.get('/api/provenance/minute',query_string={'ts':value}).status_code==400


def test_legacy_missing_hr_payload_normalization_is_distinct_from_metric_change(store):
    path,ts=store
    # Older ingestion normalized the column but retained HR0 in raw payload.
    # Rebuilding normalizes that legacy payload without changing measurements.
    with fitness.connect() as db:
        payload={'ts':ts,'hr':0,'steps':0,'active':0}
        db.execute('INSERT INTO minutes VALUES(?,?,?,?,?)',(ts,None,0,0,json.dumps(payload)))
        provenance.record_minute(db,'legacy-canonical',ts,None,dict(payload,hr=None))
    script=Path(__file__).parents[1]/'scripts'/'rebuild-minutes.py'
    result=subprocess.run([sys.executable,str(script),'--database',str(path)],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    out=json.loads(result.stdout)
    assert out['changed'] is True
    assert out['metric_changed'] is False
