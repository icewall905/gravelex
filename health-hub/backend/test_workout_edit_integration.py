"""Effective corrections must reach analytics and all completeness checks."""
import time
import uuid
from datetime import datetime
import pytest
import fitness
import workout_edits


def _metadata(data):
    if 'expected_revisions' not in data:return data
    with fitness.connect() as db: rows={row['id']:row for row in workout_edits.effective_rows(db)}
    return dict(data,expected_fingerprints={key:rows[key]['edit_fingerprint'] for key in data['expected_revisions']})


def _edit(data):return fitness.edit_workouts(_metadata(data))
def _add(data):return fitness.add_workout(_metadata(data))


def test_correction_survives_export_recomputes_coverage_and_invalidates_review(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'edits.sqlite3'))
    start=(int(time.time())//86400-2)*86400+3600
    payload={'source':'gravelex','ts':start+3600,'sessions':[{'start':start,'seconds':600,'type':'walk'}],
             'records':[{'ts':start+60*i,'hr':120} for i in range(10)]}
    fitness.ingest(payload)
    raw=fitness.summary(7)['workouts'][0]
    day=datetime.fromtimestamp(start,fitness.TZ).date().isoformat()
    fitness.confirm_day({'date':day,'status':'complete'})
    result=_edit({'operation':'edit','operation_id':str(uuid.uuid4()),'id':raw['id'],
        'expected_revisions':{raw['id']:0},'end':start+1200,'type':'run'})
    fitness.ingest(payload)
    summary=fitness.summary(7);effective=summary['workouts'][0]
    assert effective['kind']=='run' and effective['seconds']==1200
    assert effective['hr_coverage']==.5
    assert day not in summary['confirmations'] and day in result['invalidated_days']
    with fitness.connect() as db:
        assert db.execute('SELECT kind,seconds FROM workouts').fetchone()[:]==('walk',600)
    _add({'id':raw['id'],'rpe':6,'operation_id':str(uuid.uuid4()),'expected_revisions':{raw['id']:1}})
    assert fitness.summary(7)['workouts'][0]['rpe']==6
    with pytest.raises(workout_edits.ConflictError):
        _add({'id':raw['id'],'ignored':True,'operation_id':str(uuid.uuid4()),'expected_revisions':{raw['id']:1}})


def test_same_start_manual_workouts_distinct_and_retry_idempotent(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'manual.sqlite3'))
    data={'start':int(time.time())-7200,'seconds':600,'rpe':4,'type':'run','operation_id':str(uuid.uuid4())}
    first=_add(data);assert _add(data)==first
    second=_add(dict(data,operation_id=str(uuid.uuid4())))
    assert first!=second
    with fitness.connect() as db: assert db.execute('SELECT count(*) FROM workouts').fetchone()[0]==2


def test_split_children_prevent_false_rest_confirmation(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'split.sqlite3'))
    start=int(time.time())-7200
    ident=_add({'start':start,'seconds':600,'rpe':4})
    _edit({'operation':'split','operation_id':str(uuid.uuid4()),'id':ident,
        'at':start+300,'expected_revisions':{ident:0}})
    day=datetime.fromtimestamp(start,fitness.TZ).date().isoformat()
    with pytest.raises(ValueError):fitness.confirm_day({'date':day,'status':'rest'})
    with pytest.raises(ValueError):fitness.confirm_days_batch({'acknowledged':True,'days':[{'date':day,'status':'rest'}]})
    rows=fitness.summary(7)['workouts']
    assert sum(row['seconds'] for row in rows if not row['ignored'])==600


def test_import_changes_invalidate_review_but_exact_replay_does_not(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'imports.sqlite3'))
    start=(int(time.time())//86400-2)*86400+3600
    day=datetime.fromtimestamp(start,fitness.TZ).date().isoformat()
    payload={'source':'gravelex','sessions':[{'start':start,'seconds':600,'type':'walk'}]}
    fitness.confirm_day({'date':day,'status':'rest'})
    fitness.ingest(payload)
    assert day not in fitness.summary(7)['confirmations']
    fitness.confirm_day({'date':day,'status':'complete'})
    fitness.ingest(payload)
    assert day in fitness.summary(7)['confirmations']
    fitness.ingest({'source':'gravelex','sessions':[{'start':start,'seconds':900,'type':'walk'}]})
    assert day not in fitness.summary(7)['confirmations']
