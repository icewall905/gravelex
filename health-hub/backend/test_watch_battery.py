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


def test_battery_survives_same_second_report_replacement(db):
    import provenance
    provenance.ensure_schema(db)
    payload=direct(42,NOW-1)
    provenance.record_observation(db,'health_batch','gravelex',NOW,NOW,payload)
    # A later history page can replace the summary report at the same second.
    add(db,'gravelex',NOW,{'records':[]})
    b=fitness.watch_battery(db,NOW)
    assert b['percent']==42 and b['observed_at']==NOW-1


def test_series_keeps_every_observation_and_replays_dedupe(db):
    add(db,'gravelex',NOW-3600,direct(90,NOW-3600))
    add(db,'gravelex',NOW-60,direct(75,NOW-60))
    add(db,'watchapp',NOW-30,{'status':{'battery_percent':73}})
    add(db,'gravelex',NOW-30,direct(73,NOW-30))
    b=fitness.watch_battery(db,NOW)
    # Equal-timestamp dual-source observations serve as one point; direct BLE wins.
    assert [(r['ts'],r['percent']) for r in b['series']]==[(NOW-3600,90),(NOW-60,75),(NOW-30,73)]
    assert b['series']==fitness.watch_battery(db,NOW)['series']
    # Replays never duplicate rows.
    assert db.execute('SELECT COUNT(*) FROM watch_battery_readings').fetchone()[0]==4


def test_series_serves_recent_window_but_keeps_old_rows(db):
    add(db,'gravelex',NOW-8*86400,direct(50,NOW-8*86400))
    add(db,'gravelex',NOW-60,direct(75,NOW-60))
    b=fitness.watch_battery(db,NOW)
    assert [r['percent'] for r in b['series']]==[75]
    assert db.execute('SELECT COUNT(*) FROM watch_battery_readings').fetchone()[0]==2


def test_invalid_observations_never_enter_the_series(db):
    add(db,'watchapp',NOW,{'status':{'battery_percent':101}})
    add(db,'watchapp',NOW,{'status':{'battery_percent':True}})
    add(db,'gravelex',NOW,direct(60,NOW+400))
    assert fitness.watch_battery(db,NOW)['series']==[]
    assert db.execute('SELECT COUNT(*) FROM watch_battery_readings').fetchone()[0]==0


def test_ingest_records_validated_battery_in_series(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'health.sqlite3'))
    monkeypatch.setattr(fitness.time,'time',lambda:NOW)
    fitness.ingest({'source':'gravelex','ts':NOW,'watch_status':{'battery_percent':64,'observed_at':NOW-30,'source':'gravelex_ble','device_id':'watch-test'}})
    fitness.ingest({'source':'gravelex','ts':NOW,'watch_status':{'battery_percent':64,'observed_at':NOW-30,'source':'gravelex_ble','device_id':'watch-test'}})
    with fitness.connect() as db:
        rows=db.execute('SELECT observed_at,source,device_id,percent FROM watch_battery_readings').fetchall()
        assert [(r['observed_at'],r['source'],r['device_id'],r['percent']) for r in rows]==[(NOW-30,'gravelex_ble','watch-test',64)]
    b=fitness.watch_battery(fitness.connect().__enter__(),NOW)
    assert b['percent']==64 and b['series']==[{'ts':NOW-30,'percent':64}]


def test_runtime_estimate_uses_only_observed_discharge():
    s=[{'ts':NOW-20*600+600*i,'percent':100-i} for i in range(20)]
    e=fitness.battery_runtime_estimate(s)
    assert e['full_charge_hours']==16.7 and e['discharge_rate_per_hour']==6.0
    assert e['observed_discharge_hours']==3.0 and e['segments']==1


def test_runtime_estimate_trims_time_held_at_full():
    # The flat stretch at exactly 100% may be charge time; only the observed
    # discharge after it counts.
    s=[{'ts':NOW-15*600+600*i,'percent':p} for i,p in enumerate([100,100,100]+[95-5*k for k in range(13)])]
    e=fitness.battery_runtime_estimate(s)
    assert e['observed_discharge_hours']==2.0 and e['discharge_rate_per_hour']==30.0
    assert e['full_charge_hours']==3.3 and e['segments']==1


def test_runtime_estimate_excludes_charging_and_gaps():
    s=[]; t=NOW-30*600
    for i in range(12):  # genuinely observed discharge, 1% per 10 minutes
        s.append({'ts':t,'percent':100-i}); t+=600
    s.append({'ts':t,'percent':95}); t+=600   # charging: rising, ignored
    s.append({'ts':t,'percent':100}); t+=7200  # two-hour disconnect, ignored (over the 60-minute gap limit)
    for i in range(5):    # discharge resumes after the gap
        s.append({'ts':t,'percent':99-i}); t+=600
    e=fitness.battery_runtime_estimate(s)
    assert e['segments']==2 and e['observed_discharge_hours']==2.3
    assert e['discharge_rate_per_hour']==6.0 and e['full_charge_hours']==16.7


def test_runtime_estimate_counts_flat_steps_inside_a_discharge_run():
    # Integer readings at ~45-minute cadence move slower than 1% per sample;
    # flat steps between drops are real slow-discharge time.
    s=[]
    for i in range(20):
        percent=100-(i+1)//2
        s.append({'ts':NOW-20*600+600*i,'percent':percent})
    e=fitness.battery_runtime_estimate(s)
    assert e['segments']==1 and e['observed_discharge_hours']==3.0
    assert e['discharge_rate_per_hour']==3.0 and e['full_charge_hours']==33.3


def test_runtime_estimate_flat_runs_on_the_charger_are_ambiguous():
    # A run with no net drop may be a full watch sitting on the charger.
    assert fitness.battery_runtime_estimate([{'ts':NOW-3600+i*600,'percent':100} for i in range(8)]) is None


def test_runtime_estimate_needs_enough_observed_discharge():
    sparse=[{'ts':NOW-1800,'percent':100},{'ts':NOW,'percent':99}]
    assert fitness.battery_runtime_estimate(sparse) is None
    flat=[{'ts':NOW-3600+i*600,'percent':90} for i in range(8)]
    assert fitness.battery_runtime_estimate(flat) is None
    empty=[]
    assert fitness.battery_runtime_estimate(empty) is None
    # A big drop in too short a window is still not enough observation.
    quick=[{'ts':NOW-600,'percent':100},{'ts':NOW,'percent':70}]
    assert fitness.battery_runtime_estimate(quick) is None
    # A long window with almost no drop does not support an estimate either.
    shallow=[{'ts':NOW-20*600+600*i,'percent':99 if i<18 else 98} for i in range(20)]
    assert fitness.battery_runtime_estimate(shallow) is None


def test_summary_battery_carries_runtime_estimate(db):
    for i in range(20):
        add(db,'gravelex',NOW-20*600+600*i,direct(100-i,NOW-20*600+600*i))
    b=fitness.watch_battery(db,NOW)
    assert b['percent']==81 and len(b['series'])==20
    assert b['runtime_estimate']['full_charge_hours']==16.7
    assert fitness.watch_battery(db,NOW)['runtime_estimate']==b['runtime_estimate']
