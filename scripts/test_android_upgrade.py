"""Exercise Room's generated upgrade against a disposable SQLite database."""
import json
from pathlib import Path
import re
import sqlite3
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / 'libpebble3/schema/io.rebble.libpebblecommon.database.Database'


def create_database(version, schemas=SCHEMAS):
    schema = json.loads((schemas / f'{version}.json').read_text())['database']
    connection = sqlite3.connect(':memory:')
    for entity in schema['entities']:
        table = entity['tableName']
        connection.execute(entity['createSql'].replace('${TABLE_NAME}', table))
        for index in entity.get('indices', []):
            connection.execute(index['createSql'].replace('${TABLE_NAME}', table))
    return connection


def upgrade(connection, module="libpebble3", migration="Database_AutoMigration_46_51_Impl.kt"):
    generated = list((ROOT / module / 'build/generated/ksp').rglob(migration))
    if not generated:
        raise RuntimeError('Run :libpebble3:kspAndroidMain before testing the generated upgrade')
    source = generated[0].read_text()
    statements = re.findall(r'connection\.execSQL\(("(?:[^"\\]|\\.)*")\)', source)
    if not statements:
        raise RuntimeError('No generated migration statements found')
    for statement in statements:
        connection.execute(json.loads(statement))


def insert_health(connection):
    fields = connection.execute('PRAGMA table_info(health_data)').fetchall()
    values = {'timestamp': 1793923200, 'heartRate': 64, 'spo2Percent': 97, 'spo2Quality': 73}
    columns = [row[1] for row in fields]
    record = [values.get(column, 1) for column in columns]
    connection.execute(f'INSERT INTO health_data VALUES ({",".join("?" for _ in columns)})', record)
    return connection.execute('SELECT * FROM health_data').fetchall()


class AndroidUpgradeTest(unittest.TestCase):
    def test_existing_permissions_and_health_survive(self):
        with create_database(46) as connection:
            connection.executemany('INSERT INTO LockerAppPermission VALUES (?, ?, ?)', [
                ('00000000-0000-0000-0000-000000000001', 'Network', 0),
                ('00000000-0000-0000-0000-000000000001', 'Location', 1),
            ])
            permissions = connection.execute('SELECT * FROM LockerAppPermission ORDER BY permission').fetchall()
            health = insert_health(connection)
            upgrade(connection)
            self.assertEqual(permissions, connection.execute('SELECT * FROM LockerAppPermission ORDER BY permission').fetchall())
            self.assertEqual(health, connection.execute('SELECT * FROM health_data').fetchall())
            self.assertEqual([], connection.execute('SELECT * FROM AppPermission').fetchall())

    def test_upgrade_matches_fresh_schema(self):
        with create_database(46) as upgraded, create_database(51) as fresh:
            upgrade(upgraded)
            tables = lambda c: {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables(fresh), tables(upgraded))
            for table in tables(fresh):
                # ALTER TABLE appends columns; Room validates columns by name, too.
                columns = lambda c: {r[1]: r[2:] for r in c.execute(f'PRAGMA table_info("{table}")')}
                self.assertEqual(columns(fresh), columns(upgraded), table)
                self.assertEqual(fresh.execute(f'PRAGMA foreign_key_list("{table}")').fetchall(),
                                 upgraded.execute(f'PRAGMA foreign_key_list("{table}")').fetchall(), table)

    def test_installed_gravelex_upgrades_to_schema_54(self):
        app_id = '00000000-0000-0000-0000-000000000001'
        for version in (51, 52):
            with self.subTest(version=version), create_database(version) as connection:
                health = insert_health(connection)
                connection.execute('INSERT INTO LockerAppPermission VALUES (?, ?, ?)', (app_id, 'Network', 0))
                connection.execute(
                    'INSERT INTO AppPermission (appUuid, permission, granted, requestedAtMs) VALUES (?, ?, ?, ?)',
                    (app_id, 'Location', 1, 1000),
                )
                connection.execute(
                    '''INSERT INTO LockerEntryEntity (
                        recordHashcode, deleted, id, version, title, type, developerName,
                        configurable, pbwVersionCode, sideloaded, platforms, microphoneGranted
                    ) VALUES (1, 0, ?, '1', 'Watch app', 'Watchapp', 'Developer', 0, '1', 0, '[]', 1)''',
                    (app_id,),
                )
                if version == 51:
                    upgrade(connection, migration='Database_AutoMigration_51_52_Impl.kt')
                upgrade(connection, migration='Database_AutoMigration_52_54_Impl.kt')

                self.assertEqual(health, connection.execute('SELECT * FROM health_data').fetchall())
                self.assertEqual((app_id, 'Network', 0), connection.execute(
                    'SELECT appUuid, permission, granted FROM LockerAppPermission').fetchone())
                self.assertEqual((app_id, 'Location', 1, 1000, 0), connection.execute(
                    'SELECT appUuid, permission, granted, requestedAtMs, declared FROM AppPermission').fetchone())
                self.assertEqual((app_id, 1), connection.execute(
                    'SELECT id, watchPermissions FROM LockerEntryEntity').fetchone())
                for table in ('AppDataUsage', 'PluginActionLog'):
                    self.assertEqual(0, connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0])

    def test_core_metadata_upgrade_matches_fresh_schema(self):
        schemas = ROOT / 'util/schema/coredevices.database.CoreDatabase'
        with create_database(9, schemas) as upgraded, create_database(11, schemas) as fresh:
            for migration in ['CoreDatabase_AutoMigration_9_10_Impl.kt', 'CoreDatabase_AutoMigration_10_11_Impl.kt']:
                upgrade(upgraded, 'util', migration)
            tables = lambda c: {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertEqual(tables(fresh), tables(upgraded))
            for table in tables(fresh):
                columns = lambda c: {r[1]: r[2:] for r in c.execute(f'PRAGMA table_info("{table}")')}
                self.assertEqual(columns(fresh), columns(upgraded), table)


if __name__ == '__main__':
    unittest.main()
