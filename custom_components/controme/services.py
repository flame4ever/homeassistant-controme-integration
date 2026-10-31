"""Entity services of the Controme climate entities."""
from typing import Any

import voluptuous as vol
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import service

from .const import (
    DOMAIN,
    SERVICE_SET_TEMPORARY_TEMPERATURE,
    SERVICE_ACTIVATE_SCENE,
    ATTR_DURATION,
    ATTR_SCENE_ID,
    MIN_TEMPERATURE,
    MAX_TEMPERATURE,
    TEMPERATURE_STEP,
    MIN_DURATION,
    MAX_DURATION,
)


def validate_temperature(value: Any) -> float:
    """Return the temperature as float if it is within 5-30 and a multiple of 0.5."""
    if isinstance(value, bool):
        raise vol.Invalid("temperature must be a number")
    try:
        temperature = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("temperature must be a number") from err
    if not MIN_TEMPERATURE <= temperature <= MAX_TEMPERATURE:
        raise vol.Invalid(f"temperature must be between {MIN_TEMPERATURE} and {MAX_TEMPERATURE}")
    if (temperature / TEMPERATURE_STEP) % 1:
        raise vol.Invalid(f"temperature must be a multiple of {TEMPERATURE_STEP}")
    return temperature


def validate_duration(value: Any) -> int:
    """Return the duration in whole minutes if it is within 1-1440."""
    if isinstance(value, bool):
        raise vol.Invalid("duration must be a number of minutes")
    try:
        duration = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("duration must be a number of minutes") from err
    if duration % 1 or not MIN_DURATION <= duration <= MAX_DURATION:
        raise vol.Invalid(f"duration must be whole minutes between {MIN_DURATION} and {MAX_DURATION}")
    return int(duration)


def validate_scene_id(value: Any) -> int:
    """Return the scene ID as whole number >= 1."""
    if isinstance(value, bool):
        raise vol.Invalid("scene_id must be a whole number of at least 1")
    try:
        scene_id = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("scene_id must be a whole number of at least 1") from err
    if scene_id % 1 or scene_id < 1:
        raise vol.Invalid("scene_id must be a whole number of at least 1")
    return int(scene_id)


SET_TEMPORARY_TEMPERATURE_SCHEMA = {
    vol.Required(ATTR_TEMPERATURE): validate_temperature,
    vol.Optional(ATTR_DURATION): validate_duration,
}

# Only scenes that contain exactly the room of the target entity are activated
ACTIVATE_SCENE_SCHEMA = {
    vol.Required(ATTR_SCENE_ID): validate_scene_id,
    vol.Optional(ATTR_DURATION): validate_duration,
}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the entity services, they act on Controme climate entities only."""
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_TEMPORARY_TEMPERATURE,
        entity_domain=CLIMATE_DOMAIN,
        schema=SET_TEMPORARY_TEMPERATURE_SCHEMA,
        func="async_set_temporary_temperature",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_ACTIVATE_SCENE,
        entity_domain=CLIMATE_DOMAIN,
        schema=ACTIVATE_SCENE_SCHEMA,
        func="async_activate_scene",
    )
