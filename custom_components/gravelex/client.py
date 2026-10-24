"""Small read-only PH client. Never redirects credentials or logs health bodies."""
from __future__ import annotations
import asyncio
import json
import re
from urllib.parse import urlsplit, urlunsplit
import aiohttp

class GravelExError(Exception):
    """Server unavailable or incompatible."""

class GravelExAuthError(GravelExError):
    """Invalid, expired or insufficiently scoped token."""

class GravelExAccountChangedError(GravelExError):
    """Credentials point at a different account."""


def normalize_url(value: str) -> str:
    try:
        parts=urlsplit(value.strip())
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username is not None or parts.password is not None or parts.query or parts.fragment:
            raise ValueError
        _=parts.port
        if any(c.isspace() for c in value): raise ValueError
        return urlunsplit((parts.scheme,parts.netloc.lower(),parts.path.rstrip('/'),'',''))
    except (ValueError,AttributeError):
        raise GravelExError('Enter an HTTP(S) PH base URL without credentials or query parameters') from None


class GravelExClient:
    def __init__(self,session:aiohttp.ClientSession,base_url:str,token:str):
        self.base_url=normalize_url(base_url)
        if not isinstance(token,str) or not 20<len(token)<200 or any(c.isspace() for c in token):
            raise GravelExAuthError('Provide a PH read-only API token')
        self._session=session
        self._token=token

    async def _get(self,path,params=None):
        try:
            async with self._session.get(self.base_url+'/api/v1/'+path,params=params,
                    headers={'Authorization':'Bearer '+self._token,'Accept':'application/json'},
                    allow_redirects=False,timeout=aiohttp.ClientTimeout(total=25,connect=8)) as response:
                if response.status in (401,403): raise GravelExAuthError('PH rejected the token or its scopes')
                if response.status!=200: raise GravelExError('PH did not return a successful API response')
                chunks=[];size=0
                async for chunk in response.content.iter_chunked(65536):
                    size+=len(chunk)
                    if size>2*1024*1024: raise GravelExError('PH response exceeds the supported size')
                    chunks.append(chunk)
                data=json.loads(b''.join(chunks))
        except (aiohttp.ClientError,asyncio.TimeoutError,ValueError,UnicodeError):
            raise GravelExError('Could not read PH data') from None
        if not isinstance(data,dict) or data.get('api_version')!='1': raise GravelExError('Unsupported PH API; update the Health hub')
        return data

    async def async_summary(self):
        data=await self._get('summary')
        account=data.get('account');metrics=data.get('metrics')
        if not isinstance(account,dict) or not isinstance(account.get('id'),str) or not 1<=len(account['id'])<=128:
            raise GravelExError('PH account identity is missing; update the Health hub')
        if not isinstance(metrics,dict) or len(metrics)>256:
            raise GravelExError('Invalid PH metric response')
        for key,value in metrics.items():
            if not isinstance(key,str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',key) or (value is not None and not isinstance(value,dict)):
                raise GravelExError('Invalid PH metric response')
        return data

    async def async_history(self,resource,params=None):
        if resource not in ('minutes','workouts','sleep','oxygen','weights','hrv-sessions'):
            raise GravelExError('Unsupported history resource')
        return await self._get(resource,params)
