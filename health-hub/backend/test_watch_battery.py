"""Battery observations must not inherit health backfill upload freshness."""
import json
import sqlite3
import pytest
import fitness
import external_api

NOW=1792848000

@pytest.fixture
def db():
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
    conn.execute('CREATE TABLE reports(ts INTEGER,source TEXT,received INTEGER,payload TEXT)')
    yield conn
    conn.close()

def add(db,source,ts,payload,received=NOW):
    db.execute('INSERT INTO reports VALUES(?,?,?,?)',(ts,source,received,json.dumps(payload)))

def direct(percent,observed):
    return {'watch_status':{'battery_percent':percent,'observed_at':observed,'source':'gravelex_ble','device_id':'watch-test'}}

def test_no_battery_does_not_become_zero(db):
    add(db,'gravelex',NOW,{'records':[{'ts':NOW-60,'steps':0}]})
    assert fitness.watch_battery(db,NOW)['status']=='not_collected'
    assert fitness.watch_battery(db,NOW)['percent'] is None

def test_stale_legacy_is_not_refreshed_by_history(db):
    add(db,'watchapp',NOW-2*86400,{'status':{'battery_percent':70}},NOW-2*86400)
    add(db,'gravelex',NOW,{'records':[]})
    b=fitness.watch_battery(db,NOW)
    assert (b['percent'],b['last_percent'],b['status'])==(None,70,'stale')
    assert external_api._metrics({'watch_battery':b})['watch_battery'] is None

def test_observation_time_wins_over_receipt_and_preserves_zero(db):
    add(db,'gravelex',NOW-20,direct(0,NOW-20))
    add(db,'gravelex',NOW,direct(80,NOW-10000))
    add(db,'watchapp',NOW-60,{'status':{'battery_percent':60}})
    b=fitness.watch_battery(db,NOW)
    assert b['percent']==0 and b['source']=='gravelex_ble' and b['observed_at']==NOW-20
    m=external_api._metrics({'watch_battery':b})['watch_battery']
    assert m['value']==0 and m['observed_at']==NOW-20 and m['source']=='gravelex_ble'

@pytest.mark.parametrize('value',[True,-1,101,2.5,'70'])
def test_invalid_legacy_values_skipped(db,value):
    add(db,'watchapp',NOW,{'status':{'battery_percent':value}})
    assert fitness.watch_battery(db,NOW)['percent'] is None

def test_cached_observation_expires_even_after_new_upload(db):
    add(db,'gravelex',NOW,direct(75,NOW-7*3600))
    assert fitness.watch_battery(db,NOW)['status']=='stale'

def test_equal_timestamp_direct_preferred_and_future_skipped(db):
    add(db,'watchapp',NOW,{'status':{'battery_percent':20}})
    add(db,'gravelex',NOW,direct(21,NOW))
    add(db,'gravelex',NOW+400,direct(99,NOW+400))
    assert fitness.watch_battery(db,NOW)['percent']==21

@pytest.mark.parametrize('status',[
    {'battery_percent':True,'observed_at':NOW,'source':'gravelex_ble'},
    {'battery_percent':101,'observed_at':NOW,'source':'gravelex_ble'},
    {'battery_percent':50,'source':'gravelex_ble'},
    {'battery_percent':50,'observed_at':NOW,'source':'phone_battery'},
])
def test_ingestion_rejects_invalid_battery_before_writing(status,monkeypatch):
    monkeypatch.setattr(fitness.time,'time',lambda:NOW)
    with pytest.raises(ValueError):
        fitness.ingest({'source':'gravelex','ts':NOW,'watch_status':status})


def test_daily_activity_uses_only_today_and_preserves_missing_fields(db):
    db.execute('CREATE TABLE minutes(ts INTEGER,steps INTEGER,active INTEGER,payload TEXT)')
    start=int(fitness.datetime.fromtimestamp(NOW,fitness.TZ).replace(hour=0,minute=0,second=0,microsecond=0).timestamp())
    db.execute('INSERT INTO minutes VALUES(?,?,?,?)',(start-60,999,1,'{}'))
    db.execute('INSERT INTO minutes VALUES(?,?,?,?)',(start+60,0,0,'{}'))
    db.execute('INSERT INTO minutes VALUES(?,?,?,?)',(start+120,5,1,'{"distance_m":4}'))
    db.execute('INSERT INTO minutes VALUES(?,?,?,?)',(NOW+60,999,1,'{}'))
    a=fitness.current_activity(db,NOW)
    assert a['steps']==5 and a['active_seconds']==60 and a['distance_meters']==4
    assert a['active_kcal'] is None and a['observed_minutes']['steps']==2
    assert external_api._metrics({'current_activity':a})['steps']['value']==5
