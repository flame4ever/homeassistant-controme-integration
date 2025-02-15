"""Platform for climate integration."""
import logging
from .const import CONF_API_URL, CONF_HAUS_ID

_LOGGER = logging.getLogger(__name__)

from typing import Any, Optional
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import HVACMode, ClimateEntityFeature
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Controme climate platform."""
    import aiohttp
    base_url = entry.data[CONF_API_URL].rstrip("/")
    house_id = entry.data[CONF_HAUS_ID]
    endpoint = f"{base_url}/get/json/v1/{house_id}/temps/"
    session = hass.helpers.aiohttp_client.async_get_clientsession()
    try:
        async with session.get(endpoint) as response:
            if response.status != 200:
                _LOGGER.error("Error fetching floors, status %s", response.status)
                return
            data = await response.json()
    except Exception as ex:
        _LOGGER.error("Exception fetching floors: %s", ex)
        return

    entities = []
    for floor in data:
        entities.append(ContromeFloorClimate(entry.data, floor))
    async_add_entities(entities)

class ContromeFloorClimate(ClimateEntity):
    """Representation of a Controme floor as a climate entity.
    
    Diese Entität repräsentiert eine Etage (z. B. 'Keller') und fasst
    die Raumwerte (Temperatur, Solltemperatur) als Durchschnittswerte zusammen.
    Alle detaillierten Raumdaten (z. B. offsets, sensoren, etc.) werden in
    extra_state_attributes abgelegt.
    """
    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_should_poll = True

    def __init__(self, config: dict[str, Any], floor: dict) -> None:
        """Initialize the floor climate entity."""
        self._config = config
        self._floor = floor
        house_id = config.get(CONF_HAUS_ID, "unknown")
        floor_id = floor.get("id")
        self._attr_unique_id = f"controme_{house_id}_{floor_id}"
        self._attr_name = f"{floor.get('etagenname', 'Ohne Name')}"

        rooms = floor.get("raeume", [])
        if rooms:
            temp_values = [room.get("temperatur") for room in rooms if room.get("temperatur") is not None]
            soll_values = [room.get("solltemperatur") for room in rooms if room.get("solltemperatur") is not None]
            self._current_temperature = sum(temp_values) / len(temp_values) if temp_values else None
            self._target_temperature = sum(soll_values) / len(soll_values) if soll_values else None
        else:
            self._current_temperature = None
            self._target_temperature = None
        self._hvac_mode = HVACMode.OFF

    @property
    def current_temperature(self) -> Optional[float]:
        return self._current_temperature

    @property
    def target_temperature(self) -> Optional[float]:
        return self._target_temperature

    @property
    def hvac_mode(self) -> HVACMode:
        return self._hvac_mode

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"floor_data": self._floor}

    async def async_update(self) -> None:
        """Aktualisiere die Etagen-Daten aus der API."""
        house_id = self._config.get(CONF_HAUS_ID)
        base_url = self._config.get(CONF_API_URL).rstrip("/")
        endpoint = f"{base_url}/get/json/v1/{house_id}/temps/"
        session = self.hass.helpers.aiohttp_client.async_get_clientsession()
        try:
            async with session.get(endpoint) as response:
                if response.status != 200:
                    _LOGGER.error("Error updating floor data for floor %s, status: %s", self._floor.get("id"), response.status)
                    return
                data = await response.json()
                for floor in data:
                    if floor.get("id") == self._floor.get("id"):
                        self._floor = floor
                        rooms = floor.get("raeume", [])
                        if rooms:
                            temp_values = [room.get("temperatur") for room in rooms if room.get("temperatur") is not None]
                            soll_values = [room.get("solltemperatur") for room in rooms if room.get("solltemperatur") is not None]
                            self._current_temperature = sum(temp_values) / len(temp_values) if temp_values else None
                            self._target_temperature = sum(soll_values) / len(soll_values) if soll_values else None
                        break
                self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.error("Exception updating floor data for floor %s: %s", self._floor.get("id"), ex)