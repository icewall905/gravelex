import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

import accounts
import briefing
import fitness


@pytest.fixture
def db(tmp_path,monkeypatch):
    accounts.bind()
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'fitness.sqlite3'))
    yield
    accounts.bind()


def test_summary_failure_is_stored_as_error(db,monkeypatch):
    monkeypatch.setattr(briefing,'configured',lambda:True)
    def locked(days): raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(fitness,'summary',locked)
    assert briefing.run()=='error'
    with fitness.connect() as conn:
        rows=conn.execute('SELECT status,error,payload FROM briefings').fetchall()
    assert [r['status'] for r in rows]==['error']
    assert 'database is locked' in rows[0]['error']
    assert json.loads(rows[0]['payload'])['pages'] is None
    assert not briefing._running.locked()


def test_household_continues_after_one_person_fails(db,monkeypatch):
    first,second={'id':'a'*32,'username':'a','active':1},{'id':'b'*32,'username':'b','active':1}
    with accounts.as_user(second):
        fitness.ingest({'status':{'steps':100}})
    monkeypatch.setattr(accounts,'users',lambda:[first,second])
    def new_data():
        if accounts.current()['id']==first['id']: raise sqlite3.OperationalError('database is locked')
        return True
    monkeypatch.setattr(briefing,'new_data_since_last_briefing',new_data)
    ran=[]
    monkeypatch.setattr(briefing,'run',lambda:ran.append(accounts.current()['username']) or 'ok')
    briefing.run_household()
    assert ran==['b']


def test_daemon_survives_a_failed_iteration(db,monkeypatch):
    class Stop(BaseException): pass
    calls=[]
    def household(first):
        calls.append(first)
        if len(calls)==1: raise RuntimeError('boom')
        raise Stop
    monkeypatch.setattr(briefing,'_next_run',lambda now:(now,True))
    monkeypatch.setattr(briefing.time,'sleep',lambda s:None)
    monkeypatch.setattr(briefing,'run_household',household)
    monkeypatch.setattr(briefing.logging,'basicConfig',lambda **kw:None)
    with pytest.raises(Stop):
        briefing.daemon()
    assert len(calls)==2


@pytest.mark.parametrize('day',[(2026,10,24),(2026,3,28)])  # the nights before fall-back and spring-forward
def test_daemon_sleep_crosses_dst_to_local_wall_time(monkeypatch,day):
    tz=ZoneInfo('Europe/London')
    monkeypatch.setattr(fitness,'TZ',tz)
    monkeypatch.delenv('BRIEFING_TIME',raising=False)
    now=datetime(*day,5,41,tzinfo=tz)
    nxt,first=briefing._next_run(now)
    assert first
    seconds=briefing._sleep_seconds(nxt,now.timestamp())
    assert seconds==nxt.timestamp()-now.timestamp()
    woke=datetime.fromtimestamp(now.timestamp()+seconds,tz)
    assert (woke.day,woke.hour,woke.minute)==(day[2]+1,5,0)


def test_unusable_grounding_retry_keeps_first_draft(monkeypatch):
    monkeypatch.setattr(briefing,'facts',lambda summary,tz:{'score':42})
    draft={p:{'headline':'Score 42','summary':'Load 987 today','highlights':[],'focus':'','data_notes':[]} for p in briefing.PAGES}
    replies=iter([(draft,'first-model'),json.JSONDecodeError('bad','',0)])
    def chat(messages):
        reply=next(replies)
        if isinstance(reply,Exception): raise reply
        return json.loads(json.dumps(reply[0])),reply[1]
    monkeypatch.setattr(briefing,'_chat',chat)
    out=briefing.generate({},None)
    assert out['grounding']['retried'] is True
    assert out['grounding']['dropped_numbers']['today']==['987']
    assert out['model']=='first-model'
    assert out['pages']['today']['headline']=='Score 42'
    assert out['pages']['today']['summary']==''
