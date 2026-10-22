import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo
import collection_health


def db():
    result=sqlite3.connect(':memory:')
    result.executescript('''CREATE TABLE minutes(ts INTEGER,hr INTEGER); CREATE TABLE oxygen_samples(ts INTEGER,percent REAL,received INTEGER); CREATE TABLE reports(ts INTEGER,source TEXT,received INTEGER,payload TEXT); CREATE TABLE collector_reports(ts INTEGER,received INTEGER,payload TEXT); CREATE TABLE hrv_sessions(ts INTEGER,payload TEXT); CREATE TABLE sleep_sessions(start INTEGER,seconds INTEGER,kind TEXT);''')
    return result


def epoch(value):
    return int(datetime.fromisoformat(value).timestamp())


def test_empty_and_bounds():
    out=collection_health.build(db(),epoch('2026-10-22T12:00:00+02:00'),'Europe/Copenhagen',999)
    assert out['window_days']==30
    assert out['collector']['schedule_status']=='unknown'
    assert out['collector']['missed_slots'] is None
    assert out['daily'][-1]['expected_minutes']==720
    assert out['measurements']['heart_rate']['last_measured'] is None


def test_dst_days():
    for now,date,minutes in [('2026-03-30T00:00:00+02:00','2026-03-29',1380),('2026-10-26T00:00:00+01:00','2026-10-25',1500)]:
        out=collection_health.build(db(),epoch(now),'Europe/Copenhagen')
        row=next(r for r in out['daily'] if r['date']==date)
        assert row['expected_minutes']==minutes


def test_duplicate_null_future_and_empty_transport():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00')
    store.executemany('INSERT INTO minutes VALUES(?,?)',[(now-120,60),(now-119,61),(now-60,None),(now+60,70)])
    store.execute('INSERT INTO reports VALUES(?,?,?,?)',(now,'gravelex',now,'{"records":[]}'))
    out=collection_health.build(store,now,'UTC')
    assert out['daily'][-1]['hr_minutes']==1
    assert out['daily'][-1]['minute_buckets']==2
    assert out['measurements']['heart_rate']['last_measured']==now-119
    assert out['sources'][0]['last_received']==now
    assert out['latest_snapshot'] is None


def test_launch_is_not_measurement_and_schedule_tolerance():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00')
    store.execute('INSERT INTO collector_reports VALUES(?,?,?)',(now-2000,now,json.dumps({'phase':1,'nights_enabled':True,'schedule_ids':[1,2,3],'schedule_times':[now-1000,now-500,now+3600]})))
    out=collection_health.build(store,now,'UTC')
    assert out['collector']['last_saved_measurement'] is None
    assert [s['status'] for s in out['collector']['slots']]==['missed','pending']
    store.execute('INSERT INTO hrv_sessions VALUES(?,?)',(now-950,'{"context":"scheduled"}'))
    out=collection_health.build(store,now,'UTC')
    assert out['collector']['slots'][0]['status']=='saved'


def test_no_schedule_not_assumed():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00')
    store.execute('INSERT INTO collector_reports VALUES(?,?,?)',(now,now,'{"schedule_ok":3,"schedule_times":[]}'))
    assert collection_health.build(store,now,'UTC')['collector']['missed_slots'] is None


def test_sleep_future_and_private_tokens():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00')
    store.executescript('CREATE TABLE pairing_tokens(hash TEXT,expires INTEGER,scope TEXT);')
    store.executemany('INSERT INTO pairing_tokens VALUES(?,?,?)',[('do-not-leak',now+60,'history'),('other-secret',now-1,'hrv')])
    store.executemany('INSERT INTO sleep_sessions VALUES(?,?,?)',[(now-3600,1800,'sleep'),(now-60,3600,'sleep')])
    store.execute('INSERT INTO oxygen_samples VALUES(?,?,?)',(now+1,95,now))
    out=collection_health.build(store,now,'UTC')
    assert out['measurements']['sleep_end']['measured_at']==now-1800
    assert out['measurements']['oxygen']['measured_at'] is None
    assert out['pairing_scopes']==[{'scope':'history','active':1,'expired':0},{'scope':'hrv','active':0,'expired':1}]
    assert 'secret' not in json.dumps(out) and 'do-not-leak' not in json.dumps(out)


def test_repeated_hour_is_two_distinct_minutes():
    store=db(); now=epoch('2026-10-26T00:00:00+01:00')
    store.executemany('INSERT INTO minutes VALUES(?,?)',[(epoch('2026-10-25T02:15:00+02:00'),60),(epoch('2026-10-25T02:15:00+01:00'),60)])
    out=collection_health.build(store,now,'Europe/Copenhagen')
    assert next(r for r in out['daily'] if r['date']=='2026-10-25')['hr_minutes']==2


def test_hrv_only_transport_and_high_hr():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00')
    store.execute('INSERT INTO collector_reports VALUES(?,?,?)',(now-10,now,'{}'))
    store.executemany('INSERT INTO minutes VALUES(?,?)',[(now-60,300),(now-120,301)])
    out=collection_health.build(store,now,'UTC')
    assert out['transport']=={'last_received':now,'age_seconds':0}
    assert out['daily'][-1]['hr_minutes']==1
    assert out['measurements']['heart_rate']['measured_at']==now-60


def test_old_collector_only_receipt_stays_dated():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00'); old=now-30*86400
    store.execute('INSERT INTO collector_reports VALUES(?,?,?)',(old,old,'{}'))
    out=collection_health.build(store,now,'UTC',7)
    assert out['transport']=={'last_received':old,'age_seconds':30*86400}


def test_padded_failed_ids_and_replan_history():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00')
    def report(ts, slots, ids, enabled=True):
        store.execute('INSERT INTO collector_reports VALUES(?,?,?)',(ts,now,json.dumps({'nights_enabled':enabled,'schedule_times':slots,'schedule_ids':ids})))
    report(now-3000,[now-2000,now-1800,0,0,0,0],[1,-1,0,0,0,0])
    report(now-1000,[now+1000,0,0,0,0,0],[2,0,0,0,0,0])
    out=collection_health.build(store,now,'UTC')['collector']
    assert len(out['slots'])==1 and out['slots'][0]['status']=='missed'


def test_late_advertisement_and_disabled_slot_unknown():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00')
    for ts, data in [(now-4000,{'schedule_times':[now-2000],'schedule_ids':[1],'nights_enabled':True}),(now-3000,{'nights_enabled':False}),(now-500,{'schedule_times':[now-1000],'schedule_ids':[2]})]:
        store.execute('INSERT INTO collector_reports VALUES(?,?,?)',(ts,now,json.dumps(data)))
    out=collection_health.build(store,now,'UTC')['collector']
    assert [s['status'] for s in out['slots']]==['unknown','unknown']
    assert out['missed_slots']==0


def test_one_measurement_cannot_fill_two_slots():
    store=db(); now=epoch('2026-10-22T12:00:00+00:00')
    store.execute('INSERT INTO collector_reports VALUES(?,?,?)',(now-4000,now,json.dumps({'schedule_times':[now-2000,now-1800],'schedule_ids':[1,2]})))
    store.execute('INSERT INTO hrv_sessions VALUES(?,?)',(now-1900,'{"context":"scheduled"}'))
    out=collection_health.build(store,now,'UTC')['collector']
    assert out['stored']==1
