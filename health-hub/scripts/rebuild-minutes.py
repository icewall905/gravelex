#!/usr/bin/env python3
"""Preview canonical minute reconstruction; apply only with a new private backup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'backend'),str(root)]
import provenance


def fingerprint(db):
    result=hashlib.sha256()
    metrics=hashlib.sha256()
    count=0
    for row in db.execute('SELECT ts,hr,steps,active,payload FROM minutes ORDER BY ts'):
        value=list(row)
        metrics.update(provenance.canonical(value[:-1]).encode())
        value[-1]=json.loads(value[-1])
        result.update(provenance.canonical(value).encode())
        count+=1
    return {'rows':count,'sha256':result.hexdigest(),'metrics_sha256':metrics.hexdigest()}


def reconstruct(db):
    provenance.ensure_schema(db)
    provenance.seed_legacy_minutes(db)
    before=fingerprint(db)
    provenance.rebuild_minutes(db)
    after=fingerprint(db)
    return {'before':before,'after':after,'changed':before!=after,'metric_changed':before['metrics_sha256']!=after['metrics_sha256']}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True,type=Path)
    parser.add_argument('--apply',action='store_true',help='Write canonical minutes; requires --backup')
    parser.add_argument('--backup',type=Path,help='New backup path; existing files are never overwritten')
    args=parser.parse_args()
    original=args.database.resolve(strict=True)
    # Read-only source prevents accidental writes during the default preview.
    uri=original.as_uri()+'?mode=ro'
    source=sqlite3.connect(uri,uri=True,timeout=30)
    try:
        if not args.apply:
            with tempfile.TemporaryDirectory(prefix='pebble-rebuild-') as temp:
                with sqlite3.connect(str(Path(temp)/'preview.sqlite3')) as target:
                    source.backup(target)
                    out=reconstruct(target)
                    target.rollback()
            print(json.dumps({'mode':'preview',**out}))
            return
        if args.backup is None:
            parser.error('--apply requires --backup with a new private backup path')
        backup=args.backup.resolve()
        if backup==original:
            parser.error('Backup cannot be the source database')
        descriptor=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        os.close(descriptor)
        writer=sqlite3.connect(str(original),timeout=30)
        try:
            # Reserve writes while a second read connection backs up the last
            # committed state; no upload can race the reconstruction snapshot.
            writer.execute('BEGIN IMMEDIATE')
            with sqlite3.connect(str(backup)) as saved:
                source.backup(saved)
            out=reconstruct(writer)
            writer.commit()
            print(json.dumps({'mode':'applied','backup':str(backup),**out}))
        except Exception:
            writer.rollback()
            raise
        finally:
            writer.close()
    finally:
        source.close()


if __name__=='__main__':
    main()
