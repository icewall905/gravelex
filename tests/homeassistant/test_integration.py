from unittest.mock import AsyncMock,patch
import copy
import pytest
from aiohttp import web,ClientSession
from homeassistant.config_entries import SOURCE_USER,SOURCE_REAUTH
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from custom_components.gravelex.client import GravelExClient,GravelExAuthError,GravelExError
from custom_components.gravelex.const import DOMAIN

TOKEN='ph_synthetic_read_only_token_for_tests'
DATA={'api_version':'1','account':{'id':'person-a','username':'person','display_name':'Test person'},
      'metrics':{'steps_today':{'value':0,'unit':'steps','status':'observed_partial_day','estimated':False,'observed_at':1700000000},
                 'weight':None,'hrv_rmssd':None,'breathing_rate':None,'heart_rate':{'value':65,'unit':'bpm','estimated':False}}}

def entry():
    return MockConfigEntry(domain=DOMAIN,title='Test person',unique_id='http://ph.test|person-a',
        data={'url':'http://ph.test','token':TOKEN,'account_id':'person-a'},options={'poll_interval':300})

@pytest.mark.asyncio
async def test_client_rejects_redirects_and_auth(aiohttp_server,socket_enabled):
    async def summary(request):
        assert request.headers['Authorization']=='Bearer '+TOKEN
        return web.json_response(DATA)
    app=web.Application();app.router.add_get('/api/v1/summary',summary)
    server=await aiohttp_server(app)
    async with ClientSession() as session:
        client=GravelExClient(session,str(server.make_url('/')),TOKEN)
        assert (await client.async_summary())['metrics']['steps_today']['value']==0
    for status,error in [(302,GravelExError),(401,GravelExAuthError),(403,GravelExAuthError)]:
        app=web.Application()
        async def reply(request,status=status): return web.Response(status=status,headers={'Location':'http://secret-recipient.invalid'})
        app.router.add_get('/api/v1/summary',reply);server=await aiohttp_server(app)
        async with ClientSession() as session:
            with pytest.raises(error): await GravelExClient(session,str(server.make_url('/')),TOKEN).async_summary()

@pytest.mark.asyncio
async def test_setup_unknown_zero_and_new_metrics(hass,enable_custom_integrations):
    config=entry();config.add_to_hass(hass)
    with patch('custom_components.gravelex.client.GravelExClient.async_summary',new=AsyncMock(return_value=copy.deepcopy(DATA))):
        assert await hass.config_entries.async_setup(config.entry_id)
        await hass.async_block_till_done()
        states={state.name:state for state in hass.states.async_all() if state.domain=='sensor'}
        steps=next(s for s in states.values() if 'Steps Today' in s.name)
        assert steps.state=='0'
        assert steps.attributes['status']=='observed_partial_day'
        weight=next(s for s in states.values() if s.name.endswith('Weight'))
        assert weight.state=='unknown'
        assert weight.attributes['unit_of_measurement']=='kg'
        assert next(s for s in states.values() if s.name.endswith('Hrv Rmssd')).state=='unknown'
        coordinator=hass.data[DOMAIN][config.entry_id]
        updated=copy.deepcopy(DATA);updated['metrics']['weight']={'value':72.5,'unit':'kg','observed_at':'2026-10-20'}
        updated['metrics']['new_metric']={'value':3,'unit':'count'}
        coordinator.async_set_updated_data(updated)
        await hass.async_block_till_done()
        assert hass.states.get(weight.entity_id).state=='72.5'
        assert hass.states.get(weight.entity_id).attributes['observed_at']=='2026-10-20'
        assert any('New Metric' in state.name for state in hass.states.async_all())
        assert await hass.config_entries.async_unload(config.entry_id)

@pytest.mark.asyncio
async def test_config_flow_duplicate_and_options(hass,enable_custom_integrations):
    with patch('custom_components.gravelex.client.GravelExClient.async_summary',new=AsyncMock(return_value=DATA)),patch('custom_components.gravelex.async_setup_entry',return_value=True):
        result=await hass.config_entries.flow.async_init(DOMAIN,context={'source':SOURCE_USER})
        result=await hass.config_entries.flow.async_configure(result['flow_id'],{'url':'http://ph.test','token':TOKEN,'title':'Person','poll_interval':300})
        assert result['type']=='create_entry'
        config=result['result']
        again=await hass.config_entries.flow.async_init(DOMAIN,context={'source':SOURCE_USER})
        again=await hass.config_entries.flow.async_configure(again['flow_id'],{'url':'http://ph.test','token':TOKEN,'title':'Person','poll_interval':300})
        assert again['type']=='abort' and again['reason']=='already_configured'
        options=await hass.config_entries.options.async_init(config.entry_id)
        options=await hass.config_entries.options.async_configure(options['flow_id'],{'poll_interval':120})
        assert options['type']=='create_entry'

@pytest.mark.asyncio
async def test_reauth_cannot_switch_household_account(hass,enable_custom_integrations):
    config=entry();config.add_to_hass(hass)
    wrong=copy.deepcopy(DATA);wrong['account']['id']='person-b'
    with patch('custom_components.gravelex.client.GravelExClient.async_summary',new=AsyncMock(return_value=wrong)):
        result=await hass.config_entries.flow.async_init(DOMAIN,context={'source':SOURCE_REAUTH,'entry_id':config.entry_id},data=config.data)
        assert result['step_id']=='reauth_confirm'
        result=await hass.config_entries.flow.async_configure(result['flow_id'],{'token':TOKEN})
        assert result['errors']['base']=='account_changed'
        assert config.data['account_id']=='person-a'


@pytest.mark.asyncio
async def test_coordinator_refuses_account_switch_and_auth_failure(hass,enable_custom_integrations):
    from homeassistant.exceptions import ConfigEntryAuthFailed
    config=entry();config.add_to_hass(hass)
    with patch('custom_components.gravelex.client.GravelExClient.async_summary',new=AsyncMock(return_value=copy.deepcopy(DATA))):
        assert await hass.config_entries.async_setup(config.entry_id)
        await hass.async_block_till_done()
        coordinator=hass.data[DOMAIN][config.entry_id]
        wrong=copy.deepcopy(DATA);wrong['account']['id']='another-person'
        with patch.object(coordinator.client,'async_summary',new=AsyncMock(return_value=wrong)):
            with pytest.raises(ConfigEntryAuthFailed): await coordinator._async_update_data()
        with patch.object(coordinator.client,'async_summary',new=AsyncMock(side_effect=GravelExAuthError())):
            with pytest.raises(ConfigEntryAuthFailed): await coordinator._async_update_data()
        assert await hass.config_entries.async_unload(config.entry_id)


def test_credentials_cannot_be_embedded_in_url():
    for url in ['https://username:password@ph.example','https://ph.example?token=bad','file:///etc/passwd','https://ph.example/#token']:
        with pytest.raises(GravelExError): GravelExClient(None,url,TOKEN)
