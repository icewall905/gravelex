#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
mkdir -p backups
name="health-$(date -u +%Y%m%dT%H%M%SZ).sqlite3"
docker compose exec -T web python - "$name" <<'PY'
import sqlite3,sys,os
source=sqlite3.connect(os.environ.get('FITNESS_DB','/data/fitness.sqlite3'))
target=sqlite3.connect('/data/'+sys.argv[1])
source.backup(target)
target.close();source.close()
PY
docker compose cp "web:/data/$name" "backups/$name"
chmod 600 "backups/$name"
docker compose exec -T web python -c 'import os,sys; os.unlink("/data/"+sys.argv[1])' "$name"
echo "Backup saved: backups/$name"
