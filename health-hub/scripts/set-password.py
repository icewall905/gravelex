#!/usr/bin/env python3
"""Reset a household account password without printing secrets.

Run this inside the web container so FITNESS_DB points at the named volume.
The explicit --bootstrap mode is retained for a first-time environment setup;
normal resets update the account registry and invalidate that account's sessions.
"""
import argparse
import getpass
import os
from pathlib import Path
import secrets
import hashlib
import sqlite3

def generate_password_hash(password):
    salt=secrets.token_hex(8)
    digest=hashlib.scrypt(password.encode(),salt=salt.encode(),n=32768,r=8,p=1,maxmem=132*1024*1024).hex()
    return 'scrypt:32768:8:1$'+salt+'$'+digest

def update_bootstrap_env(path,password):
    values={'PH_PASSWORD_HASH':generate_password_hash(password), 'PH_SESSION_SECRET':secrets.token_urlsafe(48)}
    lines=path.read_text().splitlines() if path.exists() else []
    output=[]
    for line in lines:
        key=line.split('=',1)[0]
        if key in values:
            output.append(key+"='"+values.pop(key)+"'")
        else: output.append(line)
    output.extend(key+"='"+value+"'" for key,value in values.items())
    temporary=path.with_name(path.name+'.password-tmp')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream: stream.write('\n'.join(output)+'\n')
    os.replace(temporary,path)


def reset_account(db_path, username, password):
    registry=Path(db_path).expanduser().resolve().with_name('household.sqlite3')
    if not registry.exists():
        raise SystemExit('No household registry found; start the hub once, or use --bootstrap for first-time setup.')
    with sqlite3.connect(registry) as db:
        row=db.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()
        if not row:
            raise SystemExit('No existing household account has that username.')
        db.execute('UPDATE users SET password_hash=?, session_version=session_version+1 WHERE id=?',
                   (generate_password_hash(password),row[0]))

def read_password():
    password=getpass.getpass('New PH dashboard password: ')
    if not 12<=len(password)<=1024: raise SystemExit('Use a password from 12 to 1024 characters.')
    if password!=getpass.getpass('Repeat password: '): raise SystemExit('Passwords do not match.')
    return password


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Reset an existing household account password.')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--username', help='Existing registry username to reset')
    group.add_argument('--bootstrap', action='store_true', help='Set PH_PASSWORD_HASH in .env before first registry initialization')
    parser.add_argument('--env-file', default=os.environ.get('PH_ENV_FILE', str(Path(__file__).resolve().parents[1]/'.env')))
    args=parser.parse_args()
    password=read_password()
    if args.bootstrap:
        db_path=Path(os.environ.get('FITNESS_DB','data/fitness.sqlite3'))
        registry=db_path.expanduser().resolve().with_name('household.sqlite3')
        if registry.exists():
            raise SystemExit('A household registry already exists; use --username to reset an account.')
        update_bootstrap_env(Path(args.env_file),password)
        print('Bootstrap password hash updated in .env; restart the web service to initialize the administrator.')
    else:
        reset_account(os.environ.get('FITNESS_DB','data/fitness.sqlite3'),args.username,password)
        print('Password updated; that account’s existing sessions are invalidated.')
