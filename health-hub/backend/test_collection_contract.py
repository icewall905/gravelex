"""Diagnostics are evidence, not inferred rest or a connected-phone claim."""
import json
import time
from datetime import timezone
import fitness
import briefing


def test_summary_and_llm_distinguish_empty_transport_from_sensor_history(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'collection.sqlite3'))
    now=int(time.time())
    fitness.ingest({'ts':now-86400,'source':'watch','status':{'steps':10}})
    fitness.ingest({'ts':now,'source':'gravelex','records':[],'sessions':[]})
    result=fitness.summary(7)
    c=result['collection_health']
    assert c['transport']['age_seconds'] < 5
    assert c['measurements']['heart_rate']['measured_at'] is None
    assert c['latest_snapshot']['last_report_ts']==now-86400
    assert c['phone_backlog']['status']=='unknown'
    assert c['watch_phone_transfer']['status']=='unknown'
    assert result['confirmations']=={}
    assert all(row['status']=='unknown' for row in result['training']['history'])
    facts=briefing.facts(result,timezone.utc)
    assert facts['more']['hours_since_last_upload']==0
    assert facts['more']['collection_evidence']['measurements']['heart_rate']['measured_at'] is None
    assert facts['more']['night_recordings_planned'] is None


def test_empty_account_never_becomes_just_synced_or_exposes_pairing_secrets(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'collection.sqlite3'))
    token=fitness.issue_hrv_token('history')['token']
    result=fitness.summary(7)
    assert result['collection_health']['transport']['last_received'] is None
    assert result['collection_health']['pairing_scopes']==[{'scope':'history','active':1,'expired':0}]
    assert token not in json.dumps(result['collection_health'])
    assert briefing.facts(result,timezone.utc)['more']['hours_since_last_upload'] is None


def test_old_briefing_is_preserved_but_marked_for_refresh(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'briefings.sqlite3'))
    def save(version):
        payload={'pages':{'more':{'headline':'Old collection interpretation'}},'facts':{'facts_version':version}}
        with fitness.connect() as db:
            db.execute("INSERT INTO briefings(created,day,model,status,payload) VALUES(?,?,?,?,?)",
                       (version or 1,'2026-10-22','test','ok',json.dumps(payload)))
            return briefing.latest(db)
    assert save(None)['requires_refresh'] is True
    assert save(briefing.FACTS_VERSION)['requires_refresh'] is False
