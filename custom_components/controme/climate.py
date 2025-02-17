"""Support for Controme climate devices."""
import logging
from typing import Any
from datetime import timedelta

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)
ATTR_HUMIDITY = "current_humidity"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the Controme climate platform."""
    climate_devices = []
    base_url = entry.data.get(CONF_API_URL)
    house_id = entry.data.get(CONF_HAUS_ID)
    user = entry.data.get(CONF_USER)
    password = entry.data.get(CONF_PASSWORD)

    endpoint = f"{base_url}/get/json/v1/{house_id}/temps/"
    session = hass.helpers.aiohttp_client.async_get_clientsession()
    try:
        async with session.get(endpoint) as response:
            if response.status != 200:
                _LOGGER.error("Error fetching floors for climate, status %s", response.status)
                return
            data = await response.json()
    except Exception as ex:
        _LOGGER.exception("Exception during fetching climate data: %s", ex)
        return

    # Process all floors and rooms
    for floor in data:
        floor_id = floor.get("id")
        floor_name = floor.get("etagenname", f"Floor {floor_id}")
        rooms = floor.get("raeume", [])
        
        if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
            rooms = [floor]
            
        for room in rooms:
            room_id = room.get("id")
            if not room_id:
                room_id = f"{floor_id}_{index}"
            room_name = room.get("name", f"Room {room_id}")

            device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{house_id}_{floor_id}_{room_id}")},
                name=room_name,
                manufacturer="Controme",
                model="Thermostat API",
                via_device=(DOMAIN, f"{house_id}"),
            )

            climate_devices.append(
                ContromeClimate(
                    base_url,
                    house_id,
                    floor_id,
                    room_id,
                    room_name,
                    device_info,
                    room,
                    user,
                    password,
                )
            )

    async_add_entities(climate_devices)

class ContromeClimate(ClimateEntity):
    """Representation of a Controme Climate device."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(
        self,
        base_url: str,
        house_id: str,
        floor_id: str,
        room_id: str,
        room_name: str,
        device_info: DeviceInfo,
        room_data: dict,
        user: str,
        password: str,
    ):
        """Initialize the climate device."""
        self._base_url = base_url
        self._house_id = house_id
        self._floor_id = floor_id
        self._room_id = room_id
        self._device_info = device_info
        self._room_data = room_data
        self._user = user
        self._password = password
        self._attr_unique_id = f"{house_id}_{floor_id}_{room_id}_climate"
        self.entity_id = f"climate.controme_{room_name.lower()}"
        self._attr_name = room_name
        self._attr_current_temperature = room_data.get("temperatur")
        self._attr_target_temperature = room_data.get("solltemperatur")
        self._attr_hvac_mode = HVACMode.HEAT if room_data.get("betriebsart") == "Heating" else None
        self._attr_current_humidity = room_data.get("luftfeuchte")

    @property
    def device_info(self):
        """Return device info."""
        return self._device_info

    @property
    def extra_state_attributes(self):
        """Return the optional state attributes."""
        return {
            ATTR_HUMIDITY: self._attr_current_humidity
        }

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        session = async_get_clientsession(self.hass)
        # Remove trailing slash from base_url if present
        base_url = self._base_url.rstrip('/')
        endpoint = f"{base_url}/set/json/v1/{self._house_id}/soll/{self._room_id}/"
        
        data = {
            "user": self._user,
            "password": self._password,
            "soll": str(float(temperature))
        }
        
        try:
            # Log request details for debugging
            _LOGGER.debug("Setting temperature: URL=%s, Data=%s", endpoint, {**data, 'password': '***'})
            
            async with session.post(
                endpoint,
                data=data,
                headers={
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'Accept': 'application/json'
                }
            ) as response:
                response_text = await response.text()
                if response.status != 200:
                    if response.status == 403:
                        _LOGGER.error("Authentication failed when setting temperature. Check your credentials.")
                        _LOGGER.debug("Auth failed: URL=%s, User=%s, Response=%s", 
                                    endpoint, self._user, response_text)
                    else:
                        _LOGGER.error("Error setting temperature: status=%s, response=%s", 
                                    response.status, response_text)
                    return
                else:
                    _LOGGER.debug("Successfully set temperature: %s", response_text)
        except Exception as ex:
            _LOGGER.exception("Exception during setting temperature: %s", ex)
            return

        self._attr_target_temperature = temperature

    async def async_update(self):
        """Update the entity."""
        session = async_get_clientsession(self.hass)
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/temps/"
        
        try:
            async with session.get(endpoint) as response:
                if response.status != 200:
                    _LOGGER.error("Error updating climate: %s", response.status)
                    return
                data = await response.json()
        except Exception as ex:
            _LOGGER.exception("Exception during updating climate: %s", ex)
            return

        for floor in data:
            if floor.get("id") == self._floor_id:
                rooms = floor.get("raeume", [])
                if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
                    rooms = [floor]
                for room in rooms:
                    if room.get("id") == self._room_id:
                        self._room_data = room
                        self._attr_current_temperature = room.get("temperatur")
                        self._attr_target_temperature = room.get("solltemperatur")
                        self._attr_hvac_mode = HVACMode.HEAT if room.get("betriebsart") == "Heating" else None
                        self._attr_current_humidity = room.get("luftfeuchte")
                        return