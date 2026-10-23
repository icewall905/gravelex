from datetime import datetime,timedelta
import time
import pytest
import fitness


def test_batch_requires_acknowledgment_and_rolls_back_all_changes(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'days.sqlite3'))
    yesterday=str(datetime.now(fitness.TZ).date()-timedelta(days=1))
    with pytest.raises(ValueError):fitness.confirm_days_batch({'days':[{'date':yesterday,'status':'rest'}]})
    assert fitness.confirm_days_batch({'acknowledged':True,'days':[{'date':yesterday,'status':'rest'}]})['updated']==1
    with pytest.raises(ValueError):fitness.confirm_days_batch({'acknowledged':True,'days':[{'date':yesterday,'status':'unknown'},{'date':str(datetime.now(fitness.TZ).date()),'status':'rest'}]})
    assert fitness.summary(7)['confirmations'][yesterday]=='rest'
    fitness.confirm_days_batch({'acknowledged':True,'days':[{'date':yesterday,'status':'unknown'}]})
    assert yesterday not in fitness.summary(7)['confirmations']


def test_open_today_does_not_reset_yesterdays_complete_baseline(tmp_path,monkeypatch):
    monkeypatch.setattr(fitness,'DB_PATH',str(tmp_path/'baseline.sqlite3'))
    today=datetime.now(fitness.TZ).date()
    with fitness.connect() as db:
        for ago in range(1,43):
            db.execute('INSERT INTO day_confirmations VALUES(?,?,?)',(str(today-timedelta(days=ago)),'rest',int(time.time())))
    result=fitness.summary(42)
    assert result['training_ledger']['confirmed_consecutive_days']==42
    assert result['training']['latest']['baseline_days']==42
    assert result['training']['latest']['status']=='ready'
    assert result['training']['latest']['baseline_end']==str(today-timedelta(days=1))
    assert result['training']['latest']['chronic']==0
    assert result['training_ledger']['today']['status']=='open'
