import json
import sqlite3
import pytest
import provenance as p


def db():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE minutes(ts INTEGER PRIMARY KEY,hr INTEGER,steps INTEGER,active INTEGER,payload TEXT)')
    conn.execute('CREATE TABLE workouts(id TEXT)')
    p.ensure_schema(conn)
    return conn


def test_migrate_seed_and_rebuild_preserves_other_streams():
    conn = db()
    payload = {'ts': 100, 'hr': 70, 'steps': 4, 'active': 0, 'note': 'legacy'}
    conn.execute('INSERT INTO minutes VALUES(100,70,4,0,?)', (json.dumps(payload),))
    conn.execute("INSERT INTO workouts VALUES('keep')")
    assert p.seed_legacy_minutes(conn) == 1
    assert p.seed_legacy_minutes(conn) == 0
    p.ensure_schema(conn)
    assert p.rebuild_minutes(conn) == 1
    assert json.loads(conn.execute('SELECT payload FROM minutes').fetchone()[0]) == payload
    assert conn.execute('SELECT id FROM workouts').fetchone()[0] == 'keep'
    assert conn.execute('SELECT received FROM minute_observations').fetchone()[0] is None


def test_immutable_journal_dedup_and_first_receipt():
    conn = db()
    a = p.record_observation(conn, 'batch', 'gravelex', 100, 101, {'hr': 0})
    assert p.record_observation(conn, 'batch', 'gravelex', 100, 999, {'hr': 0}) == a
    assert conn.execute('SELECT received FROM ingest_observations').fetchone()[0] == 101
    for action in ('DELETE FROM ingest_observations', "UPDATE ingest_observations SET received=9"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(action)


@pytest.mark.parametrize('reverse', [False, True])
def test_rank_complementary_missing_zero_and_arrival_order(reverse):
    conn = db()
    observations = [('gravelex', 101, {'ts': 100, 'hr': 80}),
                    ('watch-history', 200, {'ts': 100, 'hr': 90, 'steps': 7}),
                    ('phone-history', 300, {'ts': 100, 'hr': 0, 'steps': None, 'active': 0})]
    for source, report, row in observations[::-1] if reverse else observations:
        p.record_minute(conn, source, report, 400, row)
    payload, winners = p.reconcile_minute(conn, 100)
    assert payload == {'ts': 100, 'hr': 80, 'steps': 7, 'active': 0}
    assert len(winners) == 3


def test_old_replay_cannot_promote_above_correction():
    conn = db()
    original = {'ts': 100, 'steps': 12}
    first = p.record_minute(conn, 'gravelex', 101, 102, original)
    p.record_minute(conn, 'gravelex', 110, 111, {'ts': 100, 'steps': 0})
    assert p.record_minute(conn, 'gravelex', 999, 999, original) == first
    assert p.reconcile_minute(conn, 100)[0]['steps'] == 0
    assert conn.execute('SELECT report_ts FROM minute_observations WHERE id=?', (first,)).fetchone()[0] == 101


def test_rebuild_revisions_stable_and_empty_store_safe():
    conn = db()
    conn.execute("INSERT INTO minutes VALUES(100,70,0,0,'{\"ts\":100,\"hr\":70,\"steps\":0,\"active\":0}')")
    assert p.rebuild_minutes(conn) == 0
    assert conn.execute('SELECT COUNT(*) FROM minutes').fetchone()[0] == 1
    p.seed_legacy_minutes(conn)
    p.record_minute(conn, 'gravelex', 110, 111, {'ts': 100, 'hr': 80})
    p.rebuild_minutes(conn)
    assert conn.execute('SELECT COUNT(*) FROM minute_revisions').fetchone()[0] == 1
    p.rebuild_minutes(conn)
    assert conn.execute('SELECT COUNT(*) FROM minute_revisions').fetchone()[0] == 1
    details = p.minute_details(conn, 100)
    assert details['canonical']['hr'] == 80
    assert len(details['observations']) == 2
    assert all('payload' not in item for item in details['observations'])


def test_revision_return_to_old_state_is_recorded():
    conn = db()
    a, b = {'ts': 100, 'hr': 70}, {'ts': 100, 'hr': 80}
    assert p.record_revision(conn, 100, None, a, {}, 1)
    assert p.record_revision(conn, 100, a, b, {}, 2)
    assert p.record_revision(conn, 100, b, a, {}, 3)
    assert not p.record_revision(conn, 100, a, a, {}, 4)
    assert conn.execute('SELECT COUNT(*) FROM minute_revisions').fetchone()[0] == 3


def test_same_report_second_explicit_zero_correction_and_replay():
    conn = db()
    original = {'ts': 100, 'steps': 12, 'active': 1}
    first = p.record_minute(conn, 'gravelex', 110, 111, original)
    p.record_minute(conn, 'gravelex', 110, 111, {'ts': 100, 'steps': 0, 'active': 0})
    assert p.record_minute(conn, 'gravelex', 999, 999, original) == first
    expected, winners = p.reconcile_minute(conn, 100)
    assert expected['steps'] == 0
    assert expected['active'] == 0
    p.rebuild_minutes(conn)
    p.rebuild_minutes(conn)
    assert p.reconcile_minute(conn, 100) == (expected, winners)
    assert json.loads(conn.execute('SELECT payload FROM minutes WHERE ts=100').fetchone()[0]) == expected
    assert conn.execute('SELECT COUNT(*) FROM minute_revisions').fetchone()[0] == 1


def test_replace_cannot_mutate_immutable_journal():
    conn = db()
    identity = p.record_observation(conn, 'batch', 'gravelex', 100, 101, {'hr': 0})
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('INSERT OR REPLACE INTO ingest_observations VALUES(?,?,?,?,?,?)',
                     (identity, 'batch', 'gravelex', 100, 999, '{}'))
    assert conn.execute('SELECT received FROM ingest_observations').fetchone()[0] == 101


@pytest.mark.parametrize('reverse', [False, True])
def test_unknown_sources_equal_rank_have_lexical_stable_tie(reverse):
    conn = db()
    sources = ['other-a', 'other-z']
    for source in sources[::-1] if reverse else sources:
        p.record_minute(conn, source, 110, 111, {'ts': 100, 'hr': 70 if source == 'other-a' else 80})
    assert p.reconcile_minute(conn, 100)[0]['hr'] == 80
