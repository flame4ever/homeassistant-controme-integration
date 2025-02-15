"""Constants for the Controme integration."""

from typing import Final
from homeassistant.const import Platform

# Integration domain
DOMAIN: Final = "controme"

# Configuration keys used in the web configuration
CONF_API_URL: Final = "api_url"
CONF_HAUS_ID: Final = "haus_id"
CONF_USER: Final = "user"
CONF_PASSWORD: Final = "password"

# Platforms are now defined in __init__.py

# Translation keys
KEY_TEMPERATURE = "Temperature"
KEY_TARGET_TEMPERATURE = "Target Temperature"
KEY_HUMIDITY = "Humidity"
KEY_TOTAL_OFFSET = "Total Offset"
KEY_OPERATION_MODE = "Operation Mode"
KEY_RETURN = "return"  # Used for return temperature sensors