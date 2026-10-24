"""Account-pinned UI setup and token renewal for GravelEx Health."""
from __future__ import annotations
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_TOKEN
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from .const import CONF_TITLE,CONF_URL,DEFAULT_NAME,DOMAIN,MAX_SCAN_INTERVAL,MIN_SCAN_INTERVAL
from .client import GravelExAccountChangedError,GravelExAuthError,GravelExClient,GravelExError

TOKEN=selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD))
INTERVAL=vol.All(vol.Coerce(int),vol.Range(min=MIN_SCAN_INTERVAL,max=MAX_SCAN_INTERVAL))

def _schema(defaults=None):
    defaults=defaults or {}
    return vol.Schema({vol.Required(CONF_URL,default=defaults.get(CONF_URL,'')):str,
        vol.Required(CONF_TOKEN):TOKEN,vol.Optional(CONF_TITLE,default=defaults.get(CONF_TITLE,DEFAULT_NAME)):str,
        vol.Required('poll_interval',default=defaults.get('poll_interval',300)):INTERVAL})

class GravelExConfigFlow(config_entries.ConfigFlow,domain=DOMAIN):
    VERSION=1
    async def _validate(self,url,token):
        client=GravelExClient(async_get_clientsession(self.hass),url,token)
        data=await client.async_summary()
        return client.base_url,data['account']['id'],data

    async def async_step_user(self,user_input=None):
        errors={}
        if user_input is not None:
            try:
                url,account_id,data=await self._validate(user_input[CONF_URL],user_input[CONF_TOKEN])
            except GravelExAuthError: errors['base']='invalid_auth'
            except GravelExError: errors['base']='cannot_connect'
            else:
                await self.async_set_unique_id(f'{url}|{account_id}')
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input.get(CONF_TITLE) or data['account'].get('display_name') or DEFAULT_NAME,
                    data={CONF_URL:url,CONF_TOKEN:user_input[CONF_TOKEN],'account_id':account_id,CONF_TITLE:user_input.get(CONF_TITLE) or DEFAULT_NAME},
                    options={'poll_interval':user_input['poll_interval']})
        return self.async_show_form(step_id='user',data_schema=_schema(user_input),errors=errors)

    async def async_step_reauth(self,entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self,user_input=None):
        entry=self._get_reauth_entry();errors={}
        if user_input is not None:
            try:
                _,account_id,_=await self._validate(entry.data[CONF_URL],user_input[CONF_TOKEN])
                if account_id!=entry.data['account_id']: raise GravelExAccountChangedError()
            except GravelExAuthError: errors['base']='invalid_auth'
            except GravelExAccountChangedError: errors['base']='account_changed'
            except GravelExError: errors['base']='cannot_connect'
            else:
                return self.async_update_reload_and_abort(entry,data_updates={CONF_TOKEN:user_input[CONF_TOKEN]})
        return self.async_show_form(step_id='reauth_confirm',data_schema=vol.Schema({vol.Required(CONF_TOKEN):TOKEN}),errors=errors)

    async def async_step_reconfigure(self,user_input=None):
        entry=self._get_reconfigure_entry();errors={}
        if user_input is not None:
            try:
                url,account_id,_=await self._validate(user_input[CONF_URL],user_input[CONF_TOKEN])
                if account_id!=entry.data['account_id']: raise GravelExAccountChangedError()
            except GravelExAuthError: errors['base']='invalid_auth'
            except GravelExAccountChangedError: errors['base']='account_changed'
            except GravelExError: errors['base']='cannot_connect'
            else:
                return self.async_update_reload_and_abort(entry,data_updates={CONF_URL:url,CONF_TOKEN:user_input[CONF_TOKEN],CONF_TITLE:user_input.get(CONF_TITLE) or DEFAULT_NAME},
                    options_updates={'poll_interval':user_input['poll_interval']})
        return self.async_show_form(step_id='reconfigure',data_schema=_schema({**entry.data,**entry.options}),errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return GravelExOptionsFlow()

class GravelExOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self,user_input=None):
        if user_input is not None: return self.async_create_entry(data=user_input)
        return self.async_show_form(step_id='init',data_schema=vol.Schema({vol.Required('poll_interval',default=self.config_entry.options.get('poll_interval',300)):INTERVAL}))
