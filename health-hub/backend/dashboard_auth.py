"""Versioned household sessions; upload and integration credentials stay separate."""
import os
import secrets
import threading
import time
from collections import OrderedDict
from datetime import timedelta
from flask import request, session, jsonify, redirect, send_from_directory
from werkzeug.security import check_password_hash, generate_password_hash
import accounts
_DUMMY_HASH=generate_password_hash(secrets.token_urlsafe(32))

_attempts = OrderedDict()
_lock = threading.Lock()

def install(app, web_dir):
    accounts.install_context(app)
    app.secret_key = os.environ.get('PH_SESSION_SECRET') or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_NAME='ph_session', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict',
                      SESSION_COOKIE_SECURE=os.environ.get('PUBLIC_URL','').startswith('https://'),
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))

    def configured():
        return bool(os.environ.get('PH_SESSION_SECRET') and accounts.initialize())

    def csrf_ok():
        origin = request.headers.get('Origin')
        expected = os.environ.get('PUBLIC_URL','').rstrip('/') or request.host_url.rstrip('/')
        return (request.headers.get('X-PH-Request') == '1'
                and request.headers.get('Sec-Fetch-Site') != 'cross-site'
                and (not origin or origin == expected))

    @app.before_request
    def protect():
        path = request.path
        if path.startswith('/fitness/') or path.startswith('/api/v1/') or path == '/healthz':
            return None
        if not configured():
            return jsonify(error='dashboard_setup_required'), 503
        if path in ('/login','/auth/login','/styles.css','/app.js','/sw.js','/manifest.webmanifest') or path.startswith('/icons/'):
            return None
        user=accounts.get_user(session.get('user_id')) if session.get('user_id') else None
        if not user or not user['active'] or session.get('version')!=user['session_version']:
            session.clear()
            if path.startswith('/api/') or path.startswith('/auth/'):
                return jsonify(error='login_required'), 401
            return redirect('/login')
        accounts.bind(user)
        if request.method not in ('GET','HEAD','OPTIONS'):
            if not csrf_ok():
                return jsonify(error='invalid_request_origin'), 403

    @app.get('/login')
    def login_page():
        return send_from_directory(web_dir(), 'login.html')

    @app.post('/auth/login')
    def login():
        if not csrf_ok() or not request.is_json or request.content_length is None or request.content_length > 4096:
            return jsonify(error='invalid_request'), 400
        key=request.remote_addr or 'unknown'
        now=time.monotonic()
        with _lock:
            attempts=[t for t in _attempts.get(key,[]) if now-t < 300]
            if len(attempts)>=5:
                return jsonify(error='too_many_attempts'),429,{'Retry-After':'300'}
            attempts.append(now)
            _attempts[key]=attempts
            _attempts.move_to_end(key)
            while len(_attempts)>1024: _attempts.popitem(last=False)
        body=request.get_json(silent=True)
        password=body.get('password') if isinstance(body,dict) else None
        username=body.get('username') if isinstance(body,dict) else None
        user=accounts.find_username(username) if isinstance(username,str) and len(username)<=40 else None
        digest=user['password_hash'] if user else _DUMMY_HASH
        valid=isinstance(password,str) and len(password)<=1024 and check_password_hash(digest,password)
        if not valid or not user or not user['active']:
            return jsonify(error='invalid_credentials'),401
        with _lock: _attempts.pop(key,None)
        session.clear()
        session['user_id']=user['id']
        session['version']=user['session_version']
        session.permanent=True
        return jsonify(ok=True)

    @app.post('/auth/logout')
    def logout():
        session.clear()
        response=jsonify(ok=True)
        response.headers['Clear-Site-Data']='"cache", "storage"'
        return response

    @app.after_request
    def private(response):
        response.headers['Cache-Control']='no-store'
        response.headers.setdefault('X-Frame-Options','DENY')
        return response
