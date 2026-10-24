"""Create a private, consistent snapshot of all household health databases."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile


def _databases(data_dir, primary="fitness.sqlite3"):
    data = Path(data_dir)
    candidates = [data / "household.sqlite3", data / primary]
    candidates.extend(sorted((data / "people").glob("*.sqlite3")))
    return [path for path in candidates if path.is_file()]


def _snapshot(source, destination):
    # The caller holds the separate BEGIN IMMEDIATE lock connection.
    reader = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    try:
        with sqlite3.connect(destination) as target:
            reader.backup(target)
            check = target.execute("PRAGMA quick_check").fetchone()[0]
            if check != "ok":
                raise RuntimeError(f"quick_check failed for {source}: {check}")
    finally:
        reader.close()


def create_archive(output, data_dir=None):
    configured = Path(data_dir or os.environ.get("FITNESS_DB", "/data/fitness.sqlite3")).resolve()
    data = configured if configured.is_dir() else configured.parent
    primary=configured.name if not configured.is_dir() else "fitness.sqlite3"
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="household-backup-", dir=data) as staging:
        staged = Path(staging) / "data"
        staged.mkdir()
        locks = []
        try:
            # Lock enrollment before discovering members so a new account cannot
            # appear in the registry while its database is omitted from the scan.
            registry=data / "household.sqlite3"
            if registry.is_file():
                connection=sqlite3.connect(registry,timeout=30)
                connection.execute("BEGIN IMMEDIATE")
                locks.append(connection)
            databases=_databases(data,primary)
            if not databases: raise RuntimeError(f"No household databases found in {data}")
            for source in databases:
                if source==registry: continue
                connection = sqlite3.connect(source, timeout=30)
                connection.execute("BEGIN IMMEDIATE")
                locks.append(connection)
            manifest = []
            for source in databases:
                relative = source.relative_to(data).as_posix()
                destination = staged / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                _snapshot(source, destination)
                manifest.append({"path": relative, "quick_check": "ok"})
        finally:
            for connection in reversed(locks):
                connection.rollback()
                connection.close()
        (staged / "manifest.json").write_text(json.dumps({"primary_database":primary,"files": manifest}, indent=2) + "\n")
        fd=os.open(output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:
            with tarfile.open(fileobj=stream, mode="w:gz") as archive:
                archive.add(staged, arcname="data")
    os.chmod(output, 0o600)
    return output


def main():
    parser = argparse.ArgumentParser(description="Snapshot all household SQLite databases")
    parser.add_argument("output")
    parser.add_argument("--data-dir")
    args = parser.parse_args()
    print(f"Household backup created: {create_archive(args.output, args.data_dir)}")


if __name__ == "__main__":
    main()
