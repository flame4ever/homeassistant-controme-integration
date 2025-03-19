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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from aiohttp import ClientTimeout
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity

from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = ClientTimeout(total=10)  # 10 Sekunden Timeout
ATTR_HUMIDITY = "current_humidity"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the Controme climate platform."""
    climate_devices = []
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = coordinator.data
    house_id = entry.data[CONF_HAUS_ID]

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
            room["floor_id"] = floor_id

            device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{house_id}_{floor_id}_{room_id}")},
                name=room_name,
                manufacturer="Controme",
                model="Thermostat API",
                via_device=(DOMAIN, f"{house_id}"),
            )

            climate_devices.append(
                ContromeClimate(
                    coordinator,
                    entry,
                    room,
                    device_info,
                )
            )

    async_add_entities(climate_devices)

class ContromeClimate(CoordinatorEntity, ClimateEntity):
    """Representation of a Controme Climate device."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, coordinator, config_entry, room_data, device_info):
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._base_url = config_entry.data[CONF_API_URL].rstrip('/')
        self._device_info = device_info
        self._room_data = room_data
        self._attr_name = room_data.get("name")
        self._room_id = room_data.get("id")
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        self._user = config_entry.data[CONF_USER]
        self._password = config_entry.data[CONF_PASSWORD]
        self._attr_unique_id = f"{config_entry.data[CONF_HAUS_ID]}_{self._floor_id}_{self._room_id}_climate"
        self.entity_id = f"climate.controme_{self._attr_name.lower().replace(' ', '_')}"
        self._update_from_data(room_data)

        # Set supported features
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
        )
        
        # Set temperature settings
        self._attr_target_temperature_step = 0.5
        self._attr_min_temp = 5
        self._attr_max_temp = 30
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        
        # Set HVAC modes
        self._attr_hvac_modes = [
            HVACMode.HEAT,
            HVACMode.OFF,
        ]

    def _update_from_data(self, data):
        """Update attrs from data."""
        self._attr_current_temperature = data.get("temperatur")
        self._attr_target_temperature = data.get("solltemperatur")
        self._attr_hvac_mode = HVACMode.HEAT if data.get("betriebsart") == "Heating" else None
        self._attr_current_humidity = data.get("luftfeuchte")

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        for floor in self.coordinator.data:
            if floor["id"] == self._floor_id:
                for room in floor.get("raeume", []):
                    if room["id"] == self._room_id:
                        self._update_from_data(room)
                        break
        self.async_write_ha_state()

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
                    
                    # Set local value immediately for responsive UI
                    self._attr_target_temperature = temperature
                    self.async_write_ha_state()
                    
                    # Request an immediate data refresh to update all entities
                    _LOGGER.debug("Requesting immediate data refresh after temperature change")
                    await self.coordinator.async_refresh()
                    
        except Exception as ex:
            _LOGGER.exception("Exception during setting temperature: %s", ex)
            return