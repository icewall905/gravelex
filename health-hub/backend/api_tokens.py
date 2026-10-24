"""Revocable read-only credentials. Only token hashes are persisted."""
import hashlib
import json
import secrets
import time
import uuid
from flask import Blueprint, jsonify, request
import fitness
import accounts
SCOPES=[{'id':'summary:read','label':'Current summary'}, {'id':'history:read','label':'Health history'}, {'id':'raw:read','label':'Raw HRV diagnostics'}]

def connect():
    db=fitness.connect()
    db.execute('CREATE TABLE IF NOT EXISTS api_tokens (id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL, prefix TEXT NOT NULL, scopes TEXT NOT NULL, created_at INTEGER NOT NULL, expires_at INTEGER, last_used_at INTEGER, revoked_at INTEGER)')
    db.commit()
    return db

def metadata(row):
    result=dict(row)
    result.pop('hash',None)
    result['scopes']=json.loads(result['scopes'])
    return result

def create(name, scopes, expires_in_days=90):
    if not isinstance(name,str) or not 1<=len(name.strip())<=80: raise ValueError('Provide a name of 1–80 characters')
    allowed={s['id'] for s in SCOPES}
    if not isinstance(scopes,list) or not scopes or any(not isinstance(s,str) or s not in allowed for s in scopes): raise ValueError('Choose valid read-only scopes')
    if expires_in_days is not None and (type(expires_in_days) is not int or not 1<=expires_in_days<=365): raise ValueError('Expiry must be 1–365 days or null')
    token='ph_'+secrets.token_urlsafe(32)
    now=int(time.time()); ident=uuid.uuid4().hex
    with connect() as db:
        db.execute('INSERT INTO api_tokens(id,hash,name,prefix,scopes,created_at,expires_at) VALUES(?,?,?,?,?,?,?)',(ident,hashlib.sha256(token.encode()).hexdigest(),name.strip(),token[:9],json.dumps(sorted(set(scopes))),now,now+expires_in_days*86400 if expires_in_days else None))
        row=db.execute('SELECT * FROM api_tokens WHERE id=?',(ident,)).fetchone()
    accounts.register_credential(token,'api')
    return {'token':token,'token_info':metadata(row)}

def authorize(scope):
    parts=request.headers.get('Authorization','').split()
    token=parts[1] if len(parts)==2 and parts[0].lower()=='bearer' else ''
    if not 20<len(token)<200: return jsonify(error='invalid_token'),401,{'WWW-Authenticate':'Bearer'}
    if not accounts.route_credential(token,'api'): return jsonify(error='invalid_token'),401,{'WWW-Authenticate':'Bearer'}
    now=int(time.time())
    with connect() as db:
        row=db.execute('SELECT * FROM api_tokens WHERE hash=?',(hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        if row is None or row['revoked_at'] is not None or (row['expires_at'] is not None and row['expires_at']<=now):
            return jsonify(error='invalid_token'),401,{'WWW-Authenticate':'Bearer'}
        if scope not in json.loads(row['scopes']): return jsonify(error='insufficient_scope'),403
        if row['last_used_at'] is None or now-row['last_used_at']>=60:
            db.execute('UPDATE api_tokens SET last_used_at=? WHERE id=?',(now,row['id']))
    return None

def blueprint():
    bp=Blueprint('api_tokens',__name__)
    @bp.get('/api/settings/api-tokens')
    def listing():
        with connect() as db:
            return jsonify(tokens=[metadata(r) for r in db.execute('SELECT * FROM api_tokens ORDER BY created_at DESC,id')],scopes=SCOPES)
    @bp.post('/api/settings/api-tokens')
    def issue():
        if not request.is_json or (request.content_length or 0)>16384: return jsonify(error='invalid_request'),400
        body=request.get_json(silent=True)
        if not isinstance(body,dict): return jsonify(error='invalid_request'),400
        try: return jsonify(create(body.get('name'),body.get('scopes',['summary:read']),body.get('expires_in_days',90))),201
        except ValueError as error: return jsonify(error=str(error)),400
    @bp.delete('/api/settings/api-tokens/<ident>')
    def revoke(ident):
        with connect() as db:
            row=db.execute('SELECT id FROM api_tokens WHERE id=?',(ident,)).fetchone()
            if row is None: return jsonify(error='not_found'),404
            db.execute('UPDATE api_tokens SET revoked_at=COALESCE(revoked_at,?) WHERE id=?',(int(time.time()),ident))
        return jsonify(ok=True)
    return bp
