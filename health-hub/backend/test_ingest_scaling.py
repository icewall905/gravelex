"""Session ingest must resolve each changed workout without rescanning every workout."""
import sqlite3
import time
import uuid
import fitness
import workout_edits


def _edit(data):
    with fitness.connect() as db: rows={row['id']:row for row in workout_edits.effective_rows(db)}
    data=dict(data,expected_fingerprints={key:rows[key]['edit_fingerprint'] for key in data['expected_revisions']})
    return fitness.edit_workouts(data)


def _full_scan_row(db,ident):
    return next(row for row in workout_edits.effective_rows(db) if row['id']==ident)


def _ingest_recording(path,monkeypatch,payload):
    monkeypatch.setattr(fitness,'DB_PATH',str(path))
    calls=[]
    real=fitness.invalidate_workout_days
    monkeypatch.setattr(fitness,'invalidate_workout_days',lambda db,rows:(calls.append([dict(row) for row in rows]),real(db,rows)))
    fitness.ingest(payload)
    monkeypatch.setattr(fitness,'invalidate_workout_days',real)
    with fitness.connect() as db:
        state=workout_edits.effective_rows(db)
        confirmations=db.execute('SELECT day FROM day_confirmations ORDER BY day').fetchall()
    return calls,state,[row[0] for row in confirmations]


def test_single_row_lookup_matches_full_scan_with_overlays(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'base.sqlite3'))
    start=(int(time.time())//86400-5)*86400+3600
    fitness.ingest({'source':'gravelex','sessions':[{'start':start+i*86400,'seconds':600,'type':'walk'} for i in range(3)]})
    edited,split=f'pebble:{start}:walk',f'pebble:{start+86400}:walk'
    _edit({'operation':'edit','operation_id':str(uuid.uuid4()),'id':edited,
        'expected_revisions':{edited:0},'end':start+1200,'type':'run'})
    _edit({'operation':'split','operation_id':str(uuid.uuid4()),'id':split,
        'at':start+86400+300,'expected_revisions':{split:0}})
    with fitness.connect() as db:
        assert db.execute('SELECT count(*) FROM workout_overlays WHERE created').fetchone()[0]
        for offset in range(4):
            day=fitness.datetime.fromtimestamp(start+offset*86400,fitness.TZ).date().isoformat()
            db.execute('INSERT OR REPLACE INTO day_confirmations(day,status,confirmed_at) VALUES(?,?,?)',(day,'complete',0))
    with fitness.connect() as db,sqlite3.connect(tmp_path/'reference.sqlite3') as copy: db.backup(copy)
    payload={'source':'gravelex','sessions':[{'start':start,'seconds':900,'type':'walk'},
        {'start':start+86400,'seconds':900,'type':'walk'},{'start':start+2*86400,'seconds':600,'type':'walk'},
        {'start':start+3*86400,'seconds':600,'type':'walk'}]}
    actual=_ingest_recording(tmp_path/'base.sqlite3',monkeypatch,payload)
    monkeypatch.setattr(workout_edits,'effective_row',_full_scan_row)
    expected=_ingest_recording(tmp_path/'reference.sqlite3',monkeypatch,payload)
    assert actual==expected and actual[0]
    row=next(row for row in actual[1] if row['id']==edited)
    assert row['kind']=='run' and row['seconds']==1200 and row['edit_revision']==1


def test_new_sessions_do_not_rescan_all_workouts(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'scale.sqlite3'))
    start=int(time.time())-400*86400
    fitness.ingest({'source':'gravelex','sessions':[{'start':start+i*3600,'seconds':600,'type':'run'} for i in range(200)]})
    full=[]
    real=workout_edits.effective_rows
    def counting(db,rows=None):
        if rows is None:full.append(1)
        return real(db,rows)
    monkeypatch.setattr(workout_edits,'effective_rows',counting)
    fitness.ingest({'source':'gravelex','sessions':[{'start':start+i*3600+1800,'seconds':600,'type':'run'} for i in range(200)]})
    assert len(full)<=1
    monkeypatch.setattr(workout_edits,'effective_rows',real)
    with fitness.connect() as db: assert db.execute('SELECT count(*) FROM workouts').fetchone()[0]==400
