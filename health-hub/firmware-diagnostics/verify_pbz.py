#!/usr/bin/env python3
"""Read-only PBZ integrity checks using the pinned PebbleOS CRC implementation.

This validates archive contents, not a connected watch or permission to install.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import zipfile


def verify(path, source):
    spec = importlib.util.spec_from_file_location('pebble_crc', source / 'tools/stm32_crc.py')
    crc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(crc)
    records = []
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate archive paths')
        for name in names:
            p = PurePosixPath(name)
            if p.is_absolute() or '..' in p.parts:
                raise ValueError('unsafe archive path')
        if archive.testzip() is not None:
            raise ValueError('ZIP integrity failure')
        manifests = [n for n in names if PurePosixPath(n).name == 'manifest.json']
        if not manifests:
            raise ValueError('no firmware manifests')
        for name in manifests:
            manifest = json.loads(archive.read(name))
            fw = manifest['firmware']
            if manifest['type'] != 'firmware' or fw['type'] not in ('normal', 'recovery'):
                raise ValueError('unexpected firmware type')
            if fw['hwrev'] != 'obelix_pvt':
                raise ValueError('not the reviewed Obelix PVT target')
            prefix = PurePosixPath(name).parent
            for field in ('firmware', 'resources'):
                if field not in manifest:
                    continue
                record = manifest[field]
                member = PurePosixPath(record['name'])
                if member.is_absolute() or '..' in member.parts:
                    raise ValueError('unsafe manifest member path')
                payload = archive.read(str(prefix / member))
                if len(payload) != record['size'] or crc.crc32(payload) != record['crc']:
                    raise ValueError(f'{name}: {field} size/CRC mismatch')
            records.append({'manifest': name, 'slot': fw.get('slot'), 'hwrev': fw['hwrev'],
                            'type': fw['type'], 'version': fw.get('versionTag'), 'commit': fw.get('commit')})
        slots = [r['slot'] for r in records]
        if len(records) > 1:
            if len(records) != 2 or set(slots) != {0, 1}:
                raise ValueError('expected distinct slot 0 and 1 manifests')
            if any(r['type'] != 'normal' for r in records):
                raise ValueError('dual-slot bundle must contain normal firmware only')
            if len({(r['version'], r['commit']) for r in records}) != 1:
                raise ValueError('mixed firmware versions or commits')
    return {'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'manifests': records, 'archive_and_payload_integrity': 'passed',
            'watch_compatibility': 'not checked'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pebbleos-source', required=True, type=Path)
    p.add_argument('bundles', nargs='+', type=Path)
    args = p.parse_args()
    for bundle in args.bundles:
        print(json.dumps(verify(bundle, args.pebbleos_source), sort_keys=True))

if __name__ == '__main__':
    main()
