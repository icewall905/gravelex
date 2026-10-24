#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/.."
mkdir -p backups
name="health-$(date -u +%Y%m%dT%H%M%SZ)-$$.tar.gz"
inner=".household-backup-$$.tar.gz"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
docker compose exec -T web python household_backup.py "/data/$inner"
docker compose cp "web:/data/$inner" "$staging/data.tar.gz"
docker compose exec -T web python -c 'import os,sys; os.unlink("/data/"+sys.argv[1])' "$inner"
cp .env "$staging/deployment.env"
for compose_file in compose.yaml compose.yml docker-compose.yml docker-compose.yaml; do
  if [[ -f "$compose_file" ]]; then cp "$compose_file" "$staging/compose.yaml"; break; fi
done
[[ -f "$staging/compose.yaml" ]] || { echo "Compose file not found" >&2; exit 1; }
tar -czf "backups/$name" -C "$staging" data.tar.gz deployment.env compose.yaml
chmod 600 "backups/$name"
echo "Backup saved: backups/$name"
