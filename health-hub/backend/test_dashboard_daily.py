from pathlib import Path
import pytest
from werkzeug.security import generate_password_hash
import dashboard
import dashboard_auth
import fitness


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('PH_PASSWORD_HASH', generate_password_hash('test-password-123'))
    monkeypatch.setenv('PH_SESSION_SECRET', 'test-session-secret')
    monkeypatch.setattr(fitness, 'DB_PATH', str(tmp_path / 'fitness.sqlite3'))
    monkeypatch.setattr(dashboard, 'WEB_DIR', Path(__file__).parents[1] / 'web')
    dashboard_auth._attempts.clear()
    return dashboard.app.test_client()


def login(client):
    return client.post('/auth/login', json={'username': 'admin', 'password': 'test-password-123'}, headers={'X-PH-Request': '1'})


def test_daily_and_intraday_require_session(client):
    assert client.get('/api/daily').status_code == 401
    assert client.get('/api/intraday').status_code == 401


def test_daily_range_and_validation(client):
    login(client)
    rows = client.get('/api/daily?from=2026-01-01&to=2026-01-07').get_json()['items']
    assert [r['date'] for r in rows][0] == '2026-01-01' and len(rows) == 7
    assert rows[0]['steps'] is None  # unobserved days stay empty, never zero
    assert client.get('/api/daily?from=2023-01-01&to=2026-01-01').status_code == 400
    assert client.get('/api/daily?from=2026-01-08&to=2026-01-01').status_code == 400
    assert client.get('/api/daily?from=nope').status_code == 400
    assert len(client.get('/api/daily').get_json()['items']) == 365


def test_intraday_shape(client):
    login(client)
    body = client.get('/api/intraday?date=2026-01-02').get_json()
    assert body['date'] == '2026-01-02' and body['points'] == [] and body['sleep'] == []
    assert client.get('/api/intraday?date=bad').status_code == 400
