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

# New constants
SENSOR_TYPE_CURRENT = "current"
SENSOR_TYPE_TARGET = "target"
SENSOR_TYPE_HUMIDITY = "humidity"
SENSOR_TYPE_RETURN = "return"
SENSOR_TYPE_TOTAL_OFFSET = "total_offset"
SENSOR_TYPE_OPERATION_MODE = "operation_mode"

SENSOR_TYPES = {
    SENSOR_TYPE_CURRENT: "temperatur",
    SENSOR_TYPE_TARGET: "solltemperatur",
    SENSOR_TYPE_HUMIDITY: "luftfeuchte",
    SENSOR_TYPE_TOTAL_OFFSET: "total_offset",
    SENSOR_TYPE_OPERATION_MODE: "betriebsart",
}

ENTITY_ID_MAP = {
    SENSOR_TYPE_CURRENT: "temperature",
    SENSOR_TYPE_TARGET: "target",
    SENSOR_TYPE_HUMIDITY: "humidity",
    SENSOR_TYPE_TOTAL_OFFSET: "offset",
    SENSOR_TYPE_OPERATION_MODE: "mode",
}

# Map sensor types to API data keys
VALUE_MAP = {
    SENSOR_TYPE_CURRENT: "temperatur",
    SENSOR_TYPE_TARGET: "solltemperatur",
    SENSOR_TYPE_HUMIDITY: "luftfeuchte",
    SENSOR_TYPE_TOTAL_OFFSET: "total_offset",
    SENSOR_TYPE_OPERATION_MODE: "betriebsart",
}