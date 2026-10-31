"""Constants for the Controme integration."""

from typing import Final

# Integration domain
DOMAIN: Final = "controme"

# Configuration keys used in the web configuration
CONF_API_URL: Final = "api_url"
CONF_HAUS_ID: Final = "haus_id"
CONF_USER: Final = "user"
CONF_PASSWORD: Final = "password"

# Most Controme systems have a single house with ID 1
DEFAULT_HAUS_ID: Final = "1"

# Option: sensors whose last transmission is older than this (minutes) are stale
CONF_STALE_THRESHOLD: Final = "stale_threshold"
DEFAULT_STALE_THRESHOLD: Final = 15
# Below 5 minutes the minute resolution of Controme makes the flag flicker
MIN_STALE_THRESHOLD: Final = 5
MAX_STALE_THRESHOLD: Final = 1440

# Entity services of the climate entities
SERVICE_SET_TEMPORARY_TEMPERATURE: Final = "set_temporary_temperature"
SERVICE_ACTIVATE_SCENE: Final = "activate_scene"
ATTR_DURATION: Final = "duration"
ATTR_SCENE_ID: Final = "scene_id"
# Same limits as the climate entities
MIN_TEMPERATURE: Final = 5
MAX_TEMPERATURE: Final = 30
TEMPERATURE_STEP: Final = 0.5
# Duration of temporary temperatures and scenes in minutes
MIN_DURATION: Final = 1
MAX_DURATION: Final = 1440

# Platforms are now defined in __init__.py

# New constants
SENSOR_TYPE_CURRENT = "current"
SENSOR_TYPE_TARGET = "target"
SENSOR_TYPE_HUMIDITY = "humidity"
SENSOR_TYPE_RETURN = "return"
SENSOR_TYPE_TOTAL_OFFSET = "total_offset"
SENSOR_TYPE_OPERATION_MODE = "operation_mode"
# Calculated from temperatur, solltemperatur and total_offset, so not in VALUE_MAP
SENSOR_TYPE_CONTROL_DEVIATION = "control_deviation"

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
    SENSOR_TYPE_CONTROL_DEVIATION: "control_deviation",
}

# Map sensor types to API data keys
VALUE_MAP = {
    SENSOR_TYPE_CURRENT: "temperatur",
    SENSOR_TYPE_TARGET: "solltemperatur",
    SENSOR_TYPE_HUMIDITY: "luftfeuchte",
    SENSOR_TYPE_TOTAL_OFFSET: "total_offset",
    SENSOR_TYPE_OPERATION_MODE: "betriebsart",
}