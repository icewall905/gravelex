"""Constants for the GravelEx Health integration."""

from __future__ import annotations

from datetime import timedelta
from homeassistant.const import Platform

DOMAIN = "gravelex"
NAME = "GravelEx Health"
DEFAULT_NAME = "GravelEx Health"
CONF_URL = "url"
CONF_TOKEN = "token"
CONF_TITLE = "title"
CONF_ACCOUNT_ID = "account_id"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=300)
MIN_SCAN_INTERVAL = 60
MAX_SCAN_INTERVAL = 3600
CONF_POLL_INTERVAL = "poll_interval"

PLATFORMS = [Platform.SENSOR]

