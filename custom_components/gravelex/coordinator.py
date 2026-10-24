"""Coordinator for GravelEx summary data."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import GravelExAccountChangedError, GravelExAuthError, GravelExClient, GravelExError
from .const import CONF_ACCOUNT_ID, CONF_URL, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class GravelExCoordinator(DataUpdateCoordinator[dict]):
    """Fetch and validate one account's summary."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.config_entry = entry
        self.client = GravelExClient(
            async_get_clientsession(hass), entry.data[CONF_URL], entry.data[CONF_TOKEN]
        )
        seconds = entry.options.get("poll_interval", int(DEFAULT_SCAN_INTERVAL.total_seconds()))
        super().__init__(
            hass,
            _LOGGER,
            name="GravelEx Health",
            config_entry=entry,
            update_interval=timedelta(seconds=max(60, min(3600, int(seconds)))),
        )

    async def _async_update_data(self) -> dict:
        try:
            data = await self.client.async_summary()
        except GravelExAuthError as err:
            raise ConfigEntryAuthFailed("GravelEx authentication failed") from err
        except GravelExAccountChangedError as err:
            raise ConfigEntryAuthFailed("GravelEx account changed; reconfigure this entry") from err
        except GravelExError as err:
            raise UpdateFailed("Unable to update GravelEx summary") from err
        account_id = str((data.get("account") or {}).get("id", ""))
        if not account_id or account_id != str(self.config_entry.data[CONF_ACCOUNT_ID]):
            raise ConfigEntryAuthFailed("GravelEx account changed; reconfigure this entry")
        return data
