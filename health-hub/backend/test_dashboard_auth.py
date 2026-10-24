import hashlib
import time
from pathlib import Path
import pytest
from werkzeug.security import generate_password_hash
import dashboard
import dashboard_auth
import fitness
import api_tokens

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('PH_PASSWORD_HASH',generate_password_hash('test-password-123'))
    monkeypatch.setenv('PH_SESSION_SECRET','test-session-secret')
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'fitness.sqlite3'))
    monkeypatch.setattr(dashboard,'WEB_DIR',Path(__file__).parents[1]/'web')
    dashboard_auth._attempts.clear()
    return dashboard.app.test_client()

def login(client):
    return client.post('/auth/login',json={'username':'admin','password':'test-password-123'},headers={'X-PH-Request':'1'})

def test_login_and_logout(client):
    assert client.get('/').status_code==302
    assert client.get('/api/summary').status_code==401
    assert client.get('/api/settings/api-tokens').status_code==401
    assert client.get('/healthz').status_code==200
    assert client.post('/auth/login',json={'username':'admin','password':'test-password-123'}).status_code==400
    response=login(client)
    assert response.status_code==200
    assert 'HttpOnly' in response.headers['Set-Cookie']
    assert client.get('/api/settings/api-tokens').status_code==200
    assert client.post('/auth/logout').status_code==403
    assert client.post('/auth/logout',headers={'X-PH-Request':'1'}).status_code==200
    assert client.get('/api/summary').status_code==401

def test_fail_closed_and_rate_limit(client,monkeypatch):
    monkeypatch.delenv('PH_PASSWORD_HASH')
    assert client.get('/').status_code==503
    monkeypatch.setenv('PH_PASSWORD_HASH',generate_password_hash('test-password-123'))
    for _ in range(5):
        assert client.post('/auth/login',json={'username':'admin','password':'wrong'},headers={'X-PH-Request':'1'}).status_code==401
    assert login(client).status_code==429

def test_token_security(client):
    login(client)
    headers={'X-PH-Request':'1'}
    assert client.post('/api/settings/api-tokens',json={'name':'HA'}).status_code==403
    assert client.post('/api/settings/api-tokens',json={'name':'HA'},headers={**headers,'Origin':'https://evil.example'}).status_code==403
    result=client.post('/api/settings/api-tokens',json={'name':'HA','scopes':['summary:read']},headers=headers)
    assert result.status_code==201
    issued=result.get_json(); token=issued['token']; ident=issued['token_info']['id']
    with api_tokens.connect() as db:
        row=db.execute('SELECT * FROM api_tokens').fetchone()
        assert row['hash']==hashlib.sha256(token.encode()).hexdigest()
        assert token not in str(dict(row))
    anon=dashboard.app.test_client()
    bearer={'Authorization':'Bearer '+token}
    assert anon.get('/api/settings/api-tokens',headers=bearer).status_code==401
    with dashboard.app.test_request_context(headers=bearer):
        assert api_tokens.authorize('summary:read') is None
        assert api_tokens.authorize('raw:read')[1]==403
    assert client.delete('/api/settings/api-tokens/'+ident,headers=headers).status_code==200
    with dashboard.app.test_request_context(headers=bearer):
        assert api_tokens.authorize('summary:read')[1]==401

def test_live_database_api_contract(client):
    import json
    now=int(time.time())
    with fitness.connect() as db:
        db.execute('INSERT INTO minutes(ts,hr,steps,active) VALUES(?,?,?,?)',(now-120,65,2,0))
        db.execute('INSERT INTO minutes(ts,hr,steps,active) VALUES(?,?,?,?)',(now-60,66,3,0))
        db.execute('INSERT INTO hrv_sessions(id,ts,payload) VALUES(?,?,?)',('test-session',now-90,json.dumps({'private_raw':[1,2,3],'count':0,'duration_ms':0})))
    token=api_tokens.create('test',['summary:read','history:read'])['token']
    headers={'Authorization':'Bearer '+token}
    assert client.get('/api/v1/summary',headers=headers).status_code==200
    one=client.get('/api/v1/minutes?limit=1',headers=headers).get_json()
    assert one['items'][0]['hr']==65
    cursor=one['pagination']['next_cursor']
    two=client.get('/api/v1/minutes?limit=1&cursor='+cursor,headers=headers).get_json()
    assert two['items'][0]['hr']==66
    assert client.get('/api/v1/minutes?cursor=W10',headers=headers).status_code==400
    assert client.get('/api/v1/minutes?cursor='+('a'*2050),headers=headers).status_code==400
    sessions=client.get('/api/v1/hrv-sessions',headers=headers).get_json()['items']
    assert sessions==[{'id':'test-session','ts':now-90,'count':0,'duration_ms':0}]
    assert client.get('/api/v1/hrv-sessions/test-session/raw',headers=headers).status_code==403
    raw=api_tokens.create('raw',['raw:read'])['token']
    assert client.get('/api/v1/hrv-sessions/test-session/raw',headers={'Authorization':'Bearer '+raw}).get_json()['raw']['private_raw']==[1,2,3]

def test_authenticated_browser_mutations_require_header(client,monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://health.example.org')
    login(client)
    headers={'Origin':'https://health.example.org'}
    assert client.post('/api/days',json={},headers=headers).status_code==403
    # Reaches normal validation, rather than rejecting a same-origin request.
    assert client.post('/api/days',json={},headers={**headers,'X-PH-Request':'1'}).status_code==400


def test_login_stream_without_content_length(client):
    import io
    import json
    body=json.dumps({'username':'admin','password':'test-password-123'}).encode()
    response=client.post('/auth/login', content_type='application/json',
        headers={'X-PH-Request':'1'}, environ_overrides={
            'wsgi.input':io.BytesIO(body), 'CONTENT_LENGTH':'', 'wsgi.input_terminated':True})
    assert response.status_code==200

def test_login_stream_size_is_bounded(client):
    import io
    response=client.post('/auth/login', content_type='application/json',
        headers={'X-PH-Request':'1'}, environ_overrides={
            'wsgi.input':io.BytesIO(b' ' * 5000), 'CONTENT_LENGTH':'', 'wsgi.input_terminated':True})
    assert response.status_code==413


def test_privacy_origin_requires_browser_same_origin_and_marker(client):
    body={'username':'admin','password':'test-password-123'}
    base={'X-PH-Request':'1','Origin':'null'}
    for site in ('cross-site','same-site','none',''):
        assert client.post('/auth/login',json=body,headers={**base,'Sec-Fetch-Site':site}).status_code==400
    assert client.post('/auth/login',json=body,headers={'Origin':'null','Sec-Fetch-Site':'same-origin'}).status_code==400
    assert client.post('/auth/login',json=body,headers={**base,'Sec-Fetch-Site':'same-origin'}).status_code==200
    assert client.post('/auth/logout',headers={**base,'Sec-Fetch-Site':'same-origin'}).status_code==200
    assert client.post('/auth/login',json=body,headers={'X-PH-Request':'1','Origin':'https://evil.example','Sec-Fetch-Site':'same-origin'}).status_code==400
