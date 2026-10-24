#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
if [[ -e .env ]]; then echo '.env already exists; retained without changes.'; exit 0; fi
python3 - <<'PY'
from pathlib import Path
import secrets, os, hashlib
password=secrets.token_urlsafe(24)
salt=secrets.token_hex(8)
digest=hashlib.scrypt(password.encode(),salt=salt.encode(),n=32768,r=8,p=1,maxmem=132*1024*1024).hex()
password_hash='scrypt:32768:8:1$'+salt+'$'+digest
text=Path('.env.example').read_text().replace('AUTH_TOKEN=\n','AUTH_TOKEN='+secrets.token_urlsafe(48)+'\n',1)
text=text.replace('PH_PASSWORD_HASH=\n',"PH_PASSWORD_HASH='"+password_hash+"'\n").replace('PH_SESSION_SECRET=\n','PH_SESSION_SECRET='+secrets.token_urlsafe(48)+'\n')
Path('data').mkdir(exist_ok=True)
secret_fd=os.open('data/bootstrap-password.txt',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(secret_fd,'w') as f:f.write(password+'\n')
fd=os.open('.env',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:f.write(text)
print('Created private .env with a fresh receiver token. Initial dashboard password is in data/bootstrap-password.txt. Edit deployment settings before starting.')
PY
