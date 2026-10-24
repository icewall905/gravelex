import importlib.util
import json
from pathlib import Path
import pytest
from werkzeug.security import check_password_hash

@pytest.fixture
def addon(tmp_path,monkeypatch):
    source=Path(__file__).parents[2]/'homeassistant-addon/run.py'
    spec=importlib.util.spec_from_file_location('addon_entrypoint',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,'DATA',tmp_path)
    monkeypatch.setattr(module.signal,'signal',lambda *a:None)
    calls=[]
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**kw:calls.append(('bootstrap',kw['env'].copy())))
    class Child:
        returncode=0
        def __init__(self,cmd,env):calls.append((cmd,env.copy()))
        def poll(self):return 0
        def terminate(self):pass
        def wait(self,timeout=None):return 0
    monkeypatch.setattr(module.subprocess,'Popen',Child)
    return module,tmp_path,calls

def test_first_start_requires_explicit_password(addon):
    module,path,calls=addon
    (path/'options.json').write_text('{}')
    with pytest.raises(SystemExit,match='Set initial_password'):module.main()
    assert not calls

def test_private_bootstrap_host_protection_and_restart(addon):
    module,path,calls=addon
    options={'admin_username':'owner','initial_password':'synthetic-test-password','timezone':'Europe/Copenhagen','public_url':'https://health.example.org','allowed_hosts':'homeassistant.local,10.0.0.2','enable_briefing':True,'llm_base_url':'http://llm.example:8080','llm_model':'test'}
    (path/'options.json').write_text(json.dumps(options))
    assert module.main()==1 # Unexpected child termination fails the container.
    env=calls[0][1]
    assert 'health.example.org' in env['ALLOWED_HOSTS'].split(',')
    assert '10.0.0.2' in env['ALLOWED_HOSTS'].split(',')
    assert check_password_hash(env['PH_PASSWORD_HASH'],'synthetic-test-password')
    assert len(calls)==4
    assert all(call[1].get('LLM_MODEL')=='test' for call in calls)
    secrets={name:(path/name).read_bytes() for name in ('session-secret','service-token','bootstrap-password-hash')}
    assert all((path/name).stat().st_mode&0o777==0o600 for name in secrets)
    options['initial_password']='different-ignored-password'
    (path/'options.json').write_text(json.dumps(options));(path/'household.sqlite3').touch()
    module.main()
    assert all((path/name).read_bytes()==value for name,value in secrets.items())

def test_invalid_hostname_or_subpath_is_rejected(addon):
    module,path,calls=addon
    (path/'options.json').write_text(json.dumps({'initial_password':'synthetic-test-password','allowed_hosts':'https://bad.example'}))
    with pytest.raises(SystemExit,match='allowed_hosts'):module.main()
    assert not calls
