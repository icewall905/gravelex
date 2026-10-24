"""Exercise account isolation through real browser/upload/API request paths."""
import hashlib
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from werkzeug.security import generate_password_hash
import accounts
import api_tokens
import dashboard
import dashboard_auth
import fitness

PASSWORD='household-test-password'
HEADERS={'X-PH-Request':'1'}

@pytest.fixture
def household(tmp_path,monkeypatch):
    accounts.bind()
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'fitness.sqlite3'))
    monkeypatch.setenv('PH_PASSWORD_HASH',generate_password_hash(PASSWORD))
    monkeypatch.setenv('PH_SESSION_SECRET','household-test-secret')
    monkeypatch.setenv('PH_ADMIN_USERNAME','owner')
    monkeypatch.setenv('WEARER_NAME','Owner')
    monkeypatch.delenv('HEALTH_DASHBOARD_URL',raising=False)
    monkeypatch.setattr(dashboard,'WEB_DIR',Path(__file__).parents[1]/'web')
    dashboard_auth._attempts.clear()
    yield tmp_path
    accounts.bind()

def login(username,password=PASSWORD):
    client=dashboard.app.test_client()
    client.environ_base['HTTP_X_PH_REQUEST']='1'
    assert client.post('/auth/login',json={'username':username,'password':password}).status_code==200
    return client

def member(owner,username='member'):
    result=owner.post('/api/admin/users',json={'username':username,'display_name':username.title(),'password':PASSWORD})
    assert result.status_code==201,result.get_data(as_text=True)
    return result.get_json()['user']

def pair(client,kind='history',device=None):
    result=client.post('/api/pair?kind='+kind+('&device='+device if device else ''))
    assert result.status_code==200,result.get_data(as_text=True)
    return result.get_json()['token']

def bearer(token): return {'Authorization':'Bearer '+token}

def test_existing_history_and_credentials_migrate_once(household):
    now=int(time.time())
    # Existing records and tokens predate registry bootstrap.
    with fitness.connect() as db:
        db.execute('INSERT INTO hrv_sessions VALUES(?,?,?)',('original',now,json.dumps({'count':0,'duration_ms':0,'untouched':[1,2,3]})))
        digest=hashlib.sha256(b'existing-token').hexdigest()
        db.execute('INSERT INTO pairing_tokens(hash,expires,scope) VALUES(?,?,?)',(digest,now+1000,'history'))
    original=Path(fitness.DB_PATH).read_bytes()
    owner=login('owner')
    me=owner.get('/api/me').get_json()
    assert me['user']['role']=='admin'
    assert len(me['devices'])==1
    assert accounts.initialize()
    with fitness.connect() as db:
        assert json.loads(db.execute('SELECT payload FROM hrv_sessions').fetchone()[0])['untouched']==[1,2,3]
    upload=dashboard.app.test_client().post('/fitness/records',headers=bearer('existing-token'),json={'ts':now,'records':[{'ts':now-60,'hr':70}]})
    assert upload.status_code==201
    assert len(accounts.users())==1

def test_two_accounts_same_timestamps_have_separate_history_and_api(household):
    owner=login('owner'); person=member(owner); other=login('member')
    one=pair(owner); two=pair(other)
    anon=dashboard.app.test_client(); now=int(time.time()); ts=now-60
    for token,hr in [(one,61),(two,91)]:
        assert anon.post('/fitness/records',headers=bearer(token),json={'ts':now,'user_id':'forged','records':[{'ts':ts,'hr':hr}]}).status_code==201
    assert owner.get('/api/summary').get_json()['observations'][0]['hr']==61
    summary=other.get('/api/summary').get_json()
    assert summary['observations'][0]['hr']==91
    assert summary['wearer']=='Member'
    assert summary.get('composition') is None
    t1=owner.post('/api/settings/api-tokens',json={'name':'Owner','scopes':['history:read','raw:read']}).get_json()
    t2=other.post('/api/settings/api-tokens',json={'name':'Member','scopes':['history:read','raw:read']}).get_json()
    for token,hr in [(t1['token'],61),(t2['token'],91)]:
        assert anon.get('/api/v1/minutes',headers=bearer(token)).get_json()['items'][0]['hr']==hr
    assert other.delete('/api/settings/api-tokens/'+t1['token_info']['id']).status_code==404
    assert len(other.get('/api/settings/api-tokens').get_json()['tokens'])==1
    assert Path(fitness.DB_PATH).exists()
    assert (household/'people'/ (person['id']+'.sqlite3')).exists()
    # Interleaved workers must never share mutable global identity/database paths.
    def fetch(pairing):
        token,hr=pairing
        client=dashboard.app.test_client()
        for _ in range(4):
            assert client.get('/api/v1/minutes',headers=bearer(token)).get_json()['items'][0]['hr']==hr
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(fetch,[(t1['token'],61),(t2['token'],91)]))
    assert accounts.current() is None

def test_roles_resets_disabled_accounts_and_last_admin(household):
    owner=login('owner'); me=owner.get('/api/me').get_json()['user']; person=member(owner); other=login('member')
    assert other.get('/api/admin/users').status_code==403
    assert other.post('/api/admin/users',json={}).status_code==403
    assert other.patch('/api/admin/users/'+me['id'],json={'role':'user'}).status_code==403
    assert owner.patch('/api/admin/users/'+me['id'],json={'role':'user'}).status_code==400
    assert owner.patch('/api/admin/users/'+me['id'],json={'active':False}).status_code==400
    token=pair(other)
    api=other.post('/api/settings/api-tokens',json={'name':'Read'}).get_json()['token']
    changed=owner.patch('/api/admin/users/'+person['id'],json={'password':'a-new-household-password'})
    assert changed.status_code==200
    assert other.get('/api/me').status_code==401
    other=login('member','a-new-household-password')
    assert owner.patch('/api/admin/users/'+person['id'],json={'active':False}).status_code==200
    assert other.get('/api/me').status_code==401
    anon=dashboard.app.test_client()
    assert anon.get('/fitness/records',headers=bearer(token)).status_code==401
    assert anon.get('/api/v1/summary',headers=bearer(api)).status_code==401
    assert owner.patch('/api/admin/users/'+person['id'],json={'active':True}).status_code==200
    # Re-enabling never revives the old enrollment.
    assert anon.get('/fitness/records',headers=bearer(token)).status_code==401
    assert anon.get('/api/v1/summary',headers=bearer(api)).status_code==401

def test_device_ownership_disabling_and_pairing(household):
    owner=login('owner'); person=member(owner); other=login('member')
    own=owner.get('/api/devices').get_json()['devices'][0]
    theirs=other.get('/api/devices').get_json()['devices'][0]
    assert other.patch('/api/devices/'+own['id'],json={'active':False}).status_code==404
    assert other.post('/api/pair?device='+own['id']).status_code==400
    token=pair(other,device=theirs['id'])
    response=owner.patch('/api/admin/users/'+person['id']+'/devices/'+theirs['id'],json={'active':False})
    assert response.status_code==200
    assert response.get_json()['device']['active'] is False
    assert dashboard.app.test_client().get('/fitness/records',headers=bearer(token)).status_code==401
    assert other.post('/api/pair').status_code==400
    assert other.post('/api/devices',json={'name':'Second Pebble'}).status_code==201
    assert pair(other)
    assert 'X-PH-Request' in other.get('/pair').get_data(as_text=True)

def test_external_owner_services_do_not_leak_to_new_accounts(household,monkeypatch):
    owner=login('owner'); person=member(owner); other=login('member')
    monkeypatch.setenv('HEALTH_DASHBOARD_URL','https://never-query.invalid')
    monkeypatch.setenv('HEALTH_SCALE_USER','owner')
    monkeypatch.setenv('WEIGHT_PG_DSN','must-not-connect')
    monkeypatch.setenv('WEIGHT_PG_QUERY','SELECT personal_data')
    calls=[]
    monkeypatch.setattr(dashboard,'urlopen',lambda *a,**k:calls.append(a) or None)
    import weight
    monkeypatch.setattr(weight,'sync',lambda *a,**k:calls.append('weight'))
    assert other.get('/api/summary').status_code==200
    assert calls==[]
    import app as receiver
    monkeypatch.setattr(receiver,'ha_report_status',lambda status:calls.append(status))
    token=pair(other)
    response=receiver.app.test_client().post('/health',headers=bearer(token),json={'status':{'steps':123}})
    assert response.status_code==200
    assert response.get_json()['ha_delivered'] is False
    assert calls==[]

def test_raw_sessions_and_mutations_are_scoped(household):
    owner=login('owner'); person=member(owner); other=login('member')
    now=int(time.time())
    for username,raw in [('owner','owner-only'),('member','member-only')]:
        with accounts.as_user(accounts.find_username(username)):
            with fitness.connect() as db:
                db.execute('INSERT INTO hrv_sessions VALUES(?,?,?)',('same-id',now,json.dumps({'private':raw,'count':0,'duration_ms':0})))
    tokens=[c.post('/api/settings/api-tokens',json={'name':'Raw','scopes':['raw:read']}).get_json()['token'] for c in (owner,other)]
    anon=dashboard.app.test_client()
    for token,expected in zip(tokens,['owner-only','member-only']):
        assert anon.get('/api/v1/hrv-sessions/same-id/raw',headers=bearer(token)).get_json()['raw']['private']==expected
    assert owner.put('/api/profile',json={'hr_max':170,'load_method':'hr'}).status_code==200
    assert other.get('/api/summary').get_json()['profile']['hr_max']!=170

def test_background_and_scheduled_briefings_keep_identity(household,monkeypatch):
    import briefing
    owner=login('owner'); member(owner); inactive=member(owner,'inactive')
    for username in ['owner','member','inactive']:
        with accounts.as_user(accounts.find_username(username)):
            fitness.ingest({'status':{'steps':100}})
    owner.patch('/api/admin/users/'+inactive['id'],json={'active':False})
    monkeypatch.setattr(briefing,'configured',lambda:True)
    monkeypatch.setattr(briefing,'generate',lambda summary,zone:{'model':'test','pages':[summary['wearer']],'facts':{'wearer':summary['wearer']}})
    briefing.run_household(first=True)
    for username,name in [('owner','Owner'),('member','Member')]:
        with accounts.as_user(accounts.find_username(username)):
            with fitness.connect() as db:
                saved=db.execute('SELECT payload FROM briefings').fetchall()
                assert len(saved)==1
                assert json.loads(saved[0][0])['facts']['wearer']==name
    with accounts.as_user(accounts.find_username('inactive')):
        with fitness.connect() as db: assert db.execute('SELECT COUNT(*) FROM briefings').fetchone()[0]==0
    targets=[]; observed=[]
    class QueuedThread:
        def __init__(self,target,**kwargs): self.target=target
        def start(self): targets.append(self.target)
    monkeypatch.setattr(briefing.threading,'Thread',QueuedThread)
    monkeypatch.setattr(briefing,'run',lambda: observed.append(accounts.current()['username']))
    with accounts.as_user(accounts.find_username('member')):
        assert briefing.run_in_background()=='started'
    assert accounts.current() is None
    targets[0]()
    assert observed==['member']
    assert accounts.current() is None

def test_legacy_api_token_migration_and_account_cli_reset(household):
    import importlib.util
    token='ph_existing_read_token_for_migration'
    with api_tokens.connect() as db:
        db.execute('INSERT INTO api_tokens(id,hash,name,prefix,scopes,created_at) VALUES(?,?,?,?,?,?)',('legacy',hashlib.sha256(token.encode()).hexdigest(),'Legacy','ph_ex',json.dumps(['history:read']),int(time.time())))
    owner=login('owner')
    assert dashboard.app.test_client().get('/api/v1/minutes',headers=bearer(token)).status_code==200
    module_path=Path(__file__).parents[1]/'scripts/set-password.py'
    spec=importlib.util.spec_from_file_location('password_reset_cli',module_path)
    cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)
    cli.reset_account(fitness.DB_PATH,'owner','a-replacement-password')
    assert owner.get('/api/me').status_code==401
    assert login('owner','a-replacement-password').get('/api/me').get_json()['user']['role']=='admin'

def test_no_legacy_cookie_or_owner_query_can_select_another_person(household):
    owner=login('owner'); person=member(owner); other=login('member')
    old=dashboard.app.test_client()
    with old.session_transaction() as session: session['authenticated']=True
    assert old.get('/api/summary').status_code==401
    # User-controlled owner names or paths never change the authenticated store.
    assert other.get('/api/me?user=owner&user_id='+person['id']).get_json()['user']['username']=='member'
    assert other.get('/api/v1/minutes?user=owner').status_code==401
    with accounts.as_user(accounts.find_username('member')):
        assert accounts.health_path()!=fitness.DB_PATH
        assert Path(accounts.health_path()).name==person['id']+'.sqlite3'

def test_legacy_service_key_stays_owner_bound_and_revoked(household,monkeypatch):
    import app as receiver
    owner=login('owner'); person=member(owner)
    owner_user=owner.get('/api/me').get_json()['user']
    # A second administrator can disable the owner; no privilege transfer occurs.
    owner.patch('/api/admin/users/'+person['id'],json={'role':'admin'})
    second=login('member')
    monkeypatch.setattr(receiver,'AUTH_TOKEN','legacy-service-key')
    client=receiver.app.test_client()
    assert client.get('/fitness',headers=bearer('legacy-service-key')).status_code==200
    assert second.patch('/api/admin/users/'+owner_user['id'],json={'active':False}).status_code==200
    assert client.get('/fitness',headers=bearer('legacy-service-key')).status_code==401
    assert second.patch('/api/admin/users/'+owner_user['id'],json={'active':True}).status_code==200
    assert client.get('/fitness',headers=bearer('legacy-service-key')).status_code==401

def test_ha_summary_identity_all_metrics_and_daily_missingness(household):
    owner=login('owner');person=member(owner);other=login('member')
    now=int(time.time());ts=now-60
    token=pair(other)
    payload={'records':[{'ts':ts,'hr':81,'steps':0,'active':0,'active_kcal':1.5,'resting_kcal':0.8,'distance_m':0,'light_intensity':12,'intensity':5,'hr_zone':2}]}
    assert dashboard.app.test_client().post('/fitness/records',headers=bearer(token),json=payload).status_code==201
    api=other.post('/api/settings/api-tokens',json={'name':'HA'}).get_json()['token']
    result=dashboard.app.test_client().get('/api/v1/summary',headers=bearer(api)).get_json()
    assert result['account']['id']==person['id']
    assert set(result['account'])=={'id','username','display_name'}
    metrics=result['metrics'];assert len(metrics)>=50
    assert metrics['steps_today']['value']==0
    assert metrics['active_energy_today']['value']==1.5
    assert metrics['active_energy_today']['estimated'] is True
    assert metrics['active_energy_today']['status']=='observed_partial_day'
    assert metrics['ambient_light_intensity']['value']==12
    assert metrics['heart_rate']['value']==81
    assert metrics['hrv_rmssd'] is None and metrics['breathing_rate'] is None
    assert metrics['body_fat_pct'] is None
    own_api=owner.post('/api/settings/api-tokens',json={'name':'HA owner'}).get_json()['token']
    own=dashboard.app.test_client().get('/api/v1/summary',headers=bearer(own_api)).get_json()
    assert own['metrics']['steps_today'] is None
