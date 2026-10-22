#!/usr/bin/env bash
set +x
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
if [[ -e .env ]]; then echo '.env already exists; retained without changes.'; exit 0; fi
python3 - <<'PY'
from pathlib import Path
import secrets, os
text=Path('.env.example').read_text().replace('AUTH_TOKEN=\n','AUTH_TOKEN='+secrets.token_urlsafe(48)+'\n',1)
fd=os.open('.env',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:f.write(text)
print('Created private .env with a fresh receiver token. Edit deployment settings before starting.')
PY
