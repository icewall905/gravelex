"""Household identities, device enrollment and request-local health stores.

The original database belongs to the bootstrap administrator. Every other
person gets a server-generated database path; clients never supply paths or
select the owner of an upload. Credential hashes route to their enrolled owner.
"""
from contextvars import ContextVar
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid
from werkzeug.security import generate_password_hash
from flask import Blueprint, jsonify, request

_current = ContextVar('ph_identity', default=None)
_device = ContextVar('ph_device', default=None)


def current():
    return _current.get()


def bind(user=None, device=None):
    _current.set(user)
    _device.set(device)


@contextmanager
def as_user(user):
    token=_current.set(user)
    device_token=_device.set(None)
    try: yield
    finally:
        _current.reset(token)
        _device.reset(device_token)


def base_path():
    import fitness
    return Path(fitness.DB_PATH).absolute()


def registry_path():
    return base_path().with_name('household.sqlite3')


def health_path():
    user=current()
    if not user or user.get('legacy'):
        return str(base_path())
    directory=base_path().parent/'people'
    directory.mkdir(mode=0o700, exist_ok=True)
    # IDs originate exclusively from uuid.uuid4().hex, never from URL/input.
    if not re.fullmatch('[a-f0-9]{32}',user['id']): raise ValueError('Invalid account identifier')
    return str(directory/(user['id']+'.sqlite3'))


def legacy_context():
    user=current()
    return not user or bool(user.get('legacy'))


def connect():
    path=registry_path()
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
        os.close(fd)
    except FileExistsError:
        pass
    db=sqlite3.connect(path,timeout=15)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def initialize():
    """Idempotent migration; old records/tokens stay byte-for-byte in place."""
    if not registry_path().exists() and not os.environ.get('PH_PASSWORD_HASH'):
        return False
    with connect() as db:
        ready=db.execute("SELECT 1 FROM sqlite_master WHERE name='credential_owners'").fetchone()
        if ready and db.execute('SELECT 1 FROM users LIMIT 1').fetchone(): return True
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, session_version INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL, legacy INTEGER UNIQUE)')
        db.execute('CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS credential_owners (hash TEXT NOT NULL, kind TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id), device_id TEXT REFERENCES devices(id), active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(hash,kind))')
        if db.execute('SELECT 1 FROM users LIMIT 1').fetchone(): return True
        password_hash=os.environ.get('PH_PASSWORD_HASH')
        if not password_hash: return False
        username=valid_username(os.environ.get('PH_ADMIN_USERNAME','admin'))
        name=valid_name(os.environ.get('WEARER_NAME') or 'Administrator')
        ident=uuid.uuid4().hex; device=uuid.uuid4().hex; now=int(time.time())
        db.execute('INSERT INTO users(id,username,display_name,password_hash,role,created_at,legacy) VALUES(?,?,?,?,?,?,1)',(ident,username,name,password_hash,'admin',now))
        db.execute('INSERT INTO devices(id,user_id,name,created_at) VALUES(?,?,?,?)',(device,ident,'Existing Pebble',now))
        if base_path().exists():
            with sqlite3.connect(base_path()) as old:
                tables={row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for table,kind,device_id in [('pairing_tokens','watch',device),('api_tokens','api',None)]:
                    if table in tables:
                        for (digest,) in old.execute('SELECT hash FROM '+table):
                            db.execute('INSERT OR IGNORE INTO credential_owners(hash,kind,user_id,device_id) VALUES(?,?,?,?)',(digest,kind,ident,device_id))
    return True


def valid_username(value):
    if not isinstance(value,str) or not re.fullmatch('[a-z0-9][a-z0-9._-]{2,39}',value):
        raise ValueError('Username must be 3–40 lowercase letters, numbers, dots, underscores or hyphens')
    return value


def valid_name(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=80: raise ValueError('Name must be 1–80 characters')
    return value.strip()


def valid_password(value):
    if not isinstance(value,str) or not 12<=len(value)<=1024: raise ValueError('Password must be 12–1024 characters')
    return value


def public(user):
    result={key:user[key] for key in ('id','username','display_name','role','active','created_at')}
    result['active']=bool(result['active'])
    return result


def get_user(ident):
    if not initialize(): return None
    with connect() as db:
        row=db.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone()
        return dict(row) if row else None


def bootstrap_user():
    if not initialize(): return None
    with connect() as db:
        row=db.execute('SELECT * FROM users WHERE legacy=1').fetchone()
        return dict(row) if row else None


def find_username(username):
    if not isinstance(username,str) or not initialize(): return None
    with connect() as db:
        row=db.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        return dict(row) if row else None


def users():
    if not initialize(): return []
    with connect() as db: return [dict(r) for r in db.execute('SELECT * FROM users ORDER BY created_at,id')]


def public_device(row):
    result=dict(row)
    result['active']=bool(result['active'])
    return result


def devices(user_id):
    with connect() as db: return [public_device(r) for r in db.execute('SELECT * FROM devices WHERE user_id=? ORDER BY created_at,id',(user_id,))]


def add_user(body):
    if not isinstance(body,dict): raise ValueError('Expected an account object')
    username=valid_username(body.get('username')); name=valid_name(body.get('display_name') or username)
    password=valid_password(body.get('password')); role=body.get('role','user')
    if role not in ('admin','user'): raise ValueError('Invalid role')
    ident=uuid.uuid4().hex
    digest=generate_password_hash(password)
    with connect() as db:
        if db.execute('SELECT COUNT(*) FROM users').fetchone()[0]>=100: raise ValueError('Household account limit reached')
        try:
            db.execute('INSERT INTO users(id,username,display_name,password_hash,role,created_at) VALUES(?,?,?,?,?,?)',(ident,username,name,digest,role,int(time.time())))
        except sqlite3.IntegrityError: raise ValueError('Username already exists') from None
    add_device(ident,{'name':'My Pebble'})
    return get_user(ident)


def change_user(ident,body,actor):
    if not isinstance(body,dict) or not body or set(body)-{'display_name','password','role','active'}: raise ValueError('Invalid account update')
    changes={}
    if 'display_name' in body: changes['display_name']=valid_name(body['display_name'])
    if 'password' in body: changes['password_hash']=generate_password_hash(valid_password(body['password']))
    if 'role' in body:
        if body['role'] not in ('admin','user'): raise ValueError('Invalid role')
        changes['role']=body['role']
    if 'active' in body:
        if type(body['active']) is not bool: raise ValueError('Active must be true or false')
        changes['active']=int(body['active'])
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM users WHERE id=?',(ident,)).fetchone()
        if not row: raise LookupError('Account not found')
        removing=(changes.get('active',row['active'])==0 or changes.get('role',row['role'])!='admin')
        if ident==actor['id'] and removing: raise ValueError('You cannot disable or demote your own administrator account')
        if row['role']=='admin' and row['active'] and removing and db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]<=1:
            raise ValueError('Keep at least one active administrator')
        clause=', '.join(key+'=?' for key in changes)
        invalidate=int('password_hash' in changes or changes.get('active',row['active'])!=row['active'] or changes.get('role',row['role'])!=row['role'])
        db.execute('UPDATE users SET '+clause+',session_version=session_version+? WHERE id=?',(*changes.values(),invalidate,ident))
        if changes.get('active')==0:
            db.execute('UPDATE credential_owners SET active=0 WHERE user_id=?',(ident,))
    return get_user(ident)


def add_device(user_id,body):
    if not isinstance(body,dict): raise ValueError('Expected a device object')
    name=valid_name(body.get('name'))
    ident=uuid.uuid4().hex
    with connect() as db:
        if not db.execute('SELECT 1 FROM users WHERE id=?',(user_id,)).fetchone(): raise LookupError('Account not found')
        if db.execute('SELECT COUNT(*) FROM devices WHERE user_id=?',(user_id,)).fetchone()[0]>=50: raise ValueError('Device limit reached')
        db.execute('INSERT INTO devices(id,user_id,name,created_at) VALUES(?,?,?,?)',(ident,user_id,name,int(time.time())))
        return public_device(db.execute('SELECT * FROM devices WHERE id=?',(ident,)).fetchone())


def change_device(user_id,ident,body):
    if not isinstance(body,dict) or not body or set(body)-{'name','active'}: raise ValueError('Invalid device update')
    changes={}
    if 'name' in body: changes['name']=valid_name(body['name'])
    if 'active' in body:
        if type(body['active']) is not bool: raise ValueError('Active must be true or false')
        changes['active']=int(body['active'])
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM devices WHERE id=? AND user_id=?',(ident,user_id)).fetchone(): raise LookupError('Device not found')
        db.execute('UPDATE devices SET '+','.join(k+'=?' for k in changes)+' WHERE id=? AND user_id=?',(*changes.values(),ident,user_id))
        if changes.get('active')==0: db.execute('UPDATE credential_owners SET active=0 WHERE device_id=?',(ident,))
        return public_device(db.execute('SELECT * FROM devices WHERE id=?',(ident,)).fetchone())


def enrollment_device(device_id=None):
    user=current() or bootstrap_user()
    if not user: return None
    candidates=[d for d in devices(user['id']) if d['active'] and (not device_id or d['id']==device_id)]
    if not candidates: raise ValueError('Choose an active device belonging to your account')
    return candidates[0]['id']


def register_credential(token,kind,device_id=None):
    if not initialize(): return
    user=current() or bootstrap_user()
    if not user or not user['active']: raise ValueError('Active account required')
    if kind=='watch': device_id=enrollment_device(device_id)
    digest=hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        db.execute('INSERT OR IGNORE INTO credential_owners(hash,kind,user_id,device_id) VALUES(?,?,?,?)',(digest,kind,user['id'],device_id))


def route_credential(token,kind):
    """Return False for unknown/disabled enrollments; never fall back to owner."""
    if not initialize(): return True  # Unconfigured legacy CLI/tests retain old behavior.
    digest=hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        row=db.execute('SELECT c.user_id,c.device_id FROM credential_owners c JOIN users u ON u.id=c.user_id LEFT JOIN devices d ON d.id=c.device_id WHERE c.hash=? AND c.kind=? AND c.active=1 AND u.active=1 AND (c.device_id IS NULL OR d.active=1)',(digest,kind)).fetchone()
    if not row: return False
    user=get_user(row['user_id'])
    bind(user,row['device_id'])
    return True


def install_context(app):
    @app.before_request
    def reset_identity(): bind()
    @app.teardown_request
    def clear_identity(error): bind()


def blueprint():
    bp=Blueprint('household',__name__)
    def admin():
        return current() and current()['role']=='admin'
    def body():
        if not request.is_json or (request.content_length or 0)>16384: raise ValueError('Invalid JSON request')
        return request.get_json(silent=True)
    def safe(action,status=200):
        try: return jsonify(action()),status
        except ValueError as error: return jsonify(error=str(error)),400
        except LookupError as error: return jsonify(error=str(error)),404
    @bp.get('/api/me')
    def me(): return jsonify(user=public(current()),devices=devices(current()['id']))
    @bp.get('/api/admin/users')
    def listing():
        if not admin(): return jsonify(error='admin_required'),403
        return jsonify(users=[public(u) for u in users()])
    @bp.post('/api/admin/users')
    def create():
        if not admin(): return jsonify(error='admin_required'),403
        return safe(lambda:{'user':public(add_user(body()))},201)
    @bp.patch('/api/admin/users/<ident>')
    def edit(ident):
        if not admin(): return jsonify(error='admin_required'),403
        return safe(lambda:{'user':public(change_user(ident,body(),current()))})
    @bp.route('/api/devices',methods=['GET','POST'])
    def own_devices():
        if request.method=='GET': return jsonify(devices=devices(current()['id']))
        return safe(lambda:{'device':add_device(current()['id'],body())},201)
    @bp.patch('/api/devices/<ident>')
    def own_device_edit(ident): return safe(lambda:{'device':change_device(current()['id'],ident,body())})
    @bp.route('/api/admin/users/<user_id>/devices',methods=['GET','POST'])
    def managed_devices(user_id):
        if not admin(): return jsonify(error='admin_required'),403
        if not get_user(user_id): return jsonify(error='not_found'),404
        if request.method=='GET': return jsonify(devices=devices(user_id))
        return safe(lambda:{'device':add_device(user_id,body())},201)
    @bp.patch('/api/admin/users/<user_id>/devices/<ident>')
    def managed_device_edit(user_id,ident):
        if not admin(): return jsonify(error='admin_required'),403
        return safe(lambda:{'device':change_device(user_id,ident,body())})
    return bp


def legacy_service_authorized(token):
    """Retain the owner's service key without reviving it after account disable."""
    if not initialize(): return True
    owner=bootstrap_user()
    if not owner or not owner['active']: return False
    with as_user(owner):
        register_credential(token,'service')
    return route_credential(token,'service')
