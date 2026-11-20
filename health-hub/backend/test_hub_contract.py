"""A new instance must work without personal services or a preloaded database."""
import json
from pathlib import Path
import pytest
import fitness
import dashboard

@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setattr(fitness, 'DB_PATH', str(tmp_path/'health.sqlite3'))
    monkeypatch.setattr(dashboard, 'ALLOWED_HOSTS', {'localhost'})
    monkeypatch.setattr(dashboard, 'WEB_DIR', Path(__file__).parents[1]/'web')
    monkeypatch.delenv('HEALTH_DASHBOARD_URL', raising=False)
    monkeypatch.delenv('HEALTH_SCALE_USER', raising=False)
    monkeypatch.setenv('PH_PASSWORD_HASH', __import__('werkzeug.security',fromlist=['generate_password_hash']).generate_password_hash('testing-password'))
    monkeypatch.setenv('PH_SESSION_SECRET','testing-secret')
    client=dashboard.app.test_client()
    client.environ_base['HTTP_X_PH_REQUEST']='1'
    user=__import__('accounts').bootstrap_user()
    with client.session_transaction() as session:
        session['user_id']=user['id'];session['version']=user['session_version']
    return client

def test_empty_instance_assets_config_and_no_private_environment_leaks(web, monkeypatch):
    monkeypatch.setenv('PUBLIC_URL','https://health.example.org')
    monkeypatch.setenv('SOURCE_URL','https://code.example.org/project')
    monkeypatch.setenv('HA_TOKEN','not-a-public-value')
    config=web.get('/api/config').get_json()
    assert config == {'public_url':'https://health.example.org','source_url':'https://code.example.org/project'}
    for path in ['/', '/app.js','/styles.css','/manifest.webmanifest','/sw.js','/healthz']:
        assert web.get(path).status_code == 200, path
    assert web.get('/api/oxygen').get_json()['latest'] is None
    assert web.get('/api/oxygen').get_json()['sample_count'] == 0
    assert web.get('/api/config',headers={'Host':'untrusted.example'}).status_code == 403

def test_pair_upload_deduplicates_and_retains_watch_snapshot(web):
    import time
    now=int(time.time())
    fitness.ingest({'ts':now-90,'source':'watchapp','status':{'steps':120}})
    assert web.post('/fitness/records',json={'records':[]}).status_code == 401
    token=web.post('/api/pair?kind=history').get_json()['token']
    headers={'Authorization':'Bearer '+token}
    data={'source':'gravelex','ts':now,'records':[{'ts':now-60,'hr':60,'steps':3,'active':0}],
          'oxygen':[{'ts':now-60,'percent':97,'quality':6}]}
    assert web.post('/fitness/records',json=data,headers=headers).status_code == 201
    assert web.post('/fitness/records',json=data,headers=headers).status_code == 201
    result=web.get('/api/oxygen').get_json()
    assert result['sample_count'] == 1
    assert result['latest']['percent'] == 97
    assert result['latest']['ts'] == now-60
    assert web.get('/api/summary').get_json()['latest']['status']['steps'] == 120


def test_legacy_health_scoped_auth_preserves_forwarding(web, monkeypatch):
    import app as receiver
    monkeypatch.setattr(receiver, 'AUTH_TOKEN', 'test-master')
    forwarded=[]
    monkeypatch.setattr(receiver, 'ha_report_status', lambda status: forwarded.append(status) or True)
    client=receiver.app.test_client()
    body={'ts':int(__import__('time').time()),'status':{'steps':321}}
    assert client.post('/health',json=body).status_code == 401
    wrong=web.post('/api/pair?kind=hrv').get_json()['token']
    assert client.post('/health',json=body,headers={'Authorization':'Bearer '+wrong}).status_code == 401
    history=web.post('/api/pair?kind=history').get_json()['token']
    for token in [history,'test-master']:
        result=client.post('/health',json=body,headers={'Authorization':'Bearer '+token})
        assert result.status_code == 200
        assert result.get_json()['ha_delivered'] is True
    assert forwarded == [{'steps':321},{'steps':321}]
    assert client.get('/health/watchapp.pbw?t=test-master').status_code == 404


def test_phone_workout_uses_history_scope_and_keeps_strap_metrics_out_of_watch_history(web):
    import time
    import uuid
    from datetime import datetime
    import app as receiver

    start = (int(time.time()) // 86400 - 2) * 86400 + 3600
    payload = dict(id=str(uuid.uuid4()), start=start, seconds=180, active_seconds=120,
                   type='tennis', distance_m=450, rpe=5, heart=[[0, 160, 59], [60, 180, 60]])
    route = '/fitness/phone-workouts'
    assert web.post(route, json=payload).status_code == 401
    wrong = web.post('/api/pair?kind=hrv').get_json()['token']
    assert web.post(route, headers={'Authorization': f'Bearer {wrong}'}, json=payload).status_code == 401
    token = web.post('/api/pair?kind=history').get_json()['token']
    headers = {'Authorization': f'Bearer {token}'}

    rejected = web.post(route, headers=headers, json=dict(payload, heart=[[0, 160, 61]]))
    assert rejected.status_code == 400
    for client in (web, receiver.app.test_client()):
        response = client.post(route, headers=headers, json=payload)
        assert response.status_code == 201
        assert response.get_json()['id'] == 'phone:' + payload['id']
    assert web.post(route, headers=headers, json=dict(payload, seconds=181)).status_code == 409
    with fitness.connect() as db:
        assert db.execute('SELECT count(*) FROM workouts').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM minutes').fetchone()[0] == 0

    fitness.profile({'hr_max': 200})
    summary = fitness.summary(7)
    workout, = summary['workouts']
    assert (workout['source'], workout['kind'], workout['active_seconds'], workout['distance_m']) == ('phone', 'tennis', 120, 450)
    assert workout['hr_coverage'] == .992
    assert workout['hr_load'] == 8.933
    assert workout['rpe_load'] == 10
    assert 'heart' not in workout
    zones = summary['training']['zones']
    assert zones[3]['minutes'] == .983
    assert zones[4]['minutes'] == 1
    day = datetime.fromtimestamp(start, fitness.TZ).date().isoformat()
    fitness.confirm_days_batch({'acknowledged': True, 'days': [{'date': day, 'status': 'complete'}]})
    assert web.post(route, headers=headers, json=payload).status_code == 201
    assert fitness.summary(7)['confirmations'][day] == 'complete'
