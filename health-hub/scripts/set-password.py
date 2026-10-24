#!/usr/bin/env python3
"""Set dashboard password locally, rotating sessions without printing secrets."""
import getpass
import os
from pathlib import Path
import secrets
import hashlib

def generate_password_hash(password):
    salt=secrets.token_hex(8)
    digest=hashlib.scrypt(password.encode(),salt=salt.encode(),n=32768,r=8,p=1,maxmem=132*1024*1024).hex()
    return 'scrypt:32768:8:1$'+salt+'$'+digest

def update(path,password):
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

if __name__=='__main__':
    password=getpass.getpass('New PH dashboard password: ')
    if len(password)<12: raise SystemExit('Use at least 12 characters.')
    if password!=getpass.getpass('Repeat password: '): raise SystemExit('Passwords do not match.')
    update(Path(__file__).resolve().parents[1]/'.env',password)
    print('Password updated; recreate the web container to apply it. Existing sessions will expire.')
