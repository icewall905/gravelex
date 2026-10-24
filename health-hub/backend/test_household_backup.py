import json
import sqlite3
import tarfile

from household_backup import create_archive


def _db(path, value):
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE records(value TEXT)")
        db.execute("INSERT INTO records VALUES (?)", (value,))


def test_archive_contains_all_databases_and_wal_row(tmp_path):
    (tmp_path / "people").mkdir()
    _db(tmp_path / "fitness.sqlite3", "owner")
    _db(tmp_path / "household.sqlite3", "registry")
    _db(tmp_path / "people" / "member.sqlite3", "member")
    with sqlite3.connect(tmp_path / "people" / "member.sqlite3") as db:
        db.execute("INSERT INTO records VALUES ('uncheckpointed')")
        db.commit()

    output = create_archive(tmp_path / "backup.tar.gz", tmp_path)
    assert output.stat().st_mode & 0o777 == 0o600
    with tarfile.open(output, "r:gz") as archive:
        manifest = json.load(archive.extractfile("data/manifest.json"))
        assert {entry["path"] for entry in manifest["files"]} == {
            "fitness.sqlite3", "household.sqlite3", "people/member.sqlite3"
        }
        restored = tmp_path / "restored.sqlite3"
        restored.write_bytes(archive.extractfile("data/people/member.sqlite3").read())
        member = sqlite3.connect(restored)
        assert member.execute("SELECT value FROM records ORDER BY rowid").fetchall()[-1] == ("uncheckpointed",)

def test_configured_primary_filename_is_preserved(tmp_path,monkeypatch):
    primary=tmp_path/'custom-health.sqlite3'
    _db(primary,'custom-owner')
    monkeypatch.setenv('FITNESS_DB',str(primary))
    archive_path=create_archive(tmp_path/'export.tar.gz')
    with tarfile.open(archive_path,'r:gz') as archive:
        manifest=json.load(archive.extractfile('data/manifest.json'))
        assert manifest['primary_database']=='custom-health.sqlite3'
        assert manifest['files']==[{'path':'custom-health.sqlite3','quick_check':'ok'}]
