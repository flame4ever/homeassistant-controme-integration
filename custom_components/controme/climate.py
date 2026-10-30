"""Support for Controme climate devices."""
import logging
from typing import Any
from datetime import timedelta

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from aiohttp import ClientError, ClientTimeout
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.util import slugify

from .coordinator import ContromeConfigEntry
from .helpers import find_room, iter_rooms, to_float
from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = ClientTimeout(total=10)  # 10 Sekunden Timeout
ATTR_HUMIDITY = "current_humidity"

async def async_setup_entry(hass: HomeAssistant, entry: ContromeConfigEntry, async_add_entities):
    """Set up the Controme climate platform."""
    climate_devices = []
    coordinator = entry.runtime_data
    data = coordinator.data
    house_id = entry.data[CONF_HAUS_ID]

    # Process all floors and rooms
    for floor_id, room_id, room in iter_rooms(data):
        room_name = room.get("name") or f"Room {room_id}"
        room["floor_id"] = floor_id
        room["room_id"] = room_id

        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{house_id}_{floor_id}_{room_id}")},
            name=room_name,
            manufacturer="Controme",
            model="Thermostat API",
            via_device_id=coordinator.hub_device_id,
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
        self._room_id = room_data.get("room_id", room_data.get("id"))
        self._attr_name = room_data.get("name") or f"Room {self._room_id}"
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        self._user = config_entry.data[CONF_USER]
        self._password = config_entry.data[CONF_PASSWORD]
        self._attr_unique_id = f"{config_entry.data[CONF_HAUS_ID]}_{self._floor_id}_{self._room_id}_climate"
        self.entity_id = f"climate.controme_{slugify(self._attr_name)}"
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
        
        # Switching rooms off is not implemented, so only heating is offered
        self._attr_hvac_modes = [HVACMode.HEAT]
        self._attr_hvac_mode = HVACMode.HEAT

    def _update_from_data(self, data):
        """Update attrs from data."""
        self._attr_current_temperature = to_float(data.get("temperatur"))
        self._attr_target_temperature = to_float(data.get("solltemperatur"))
        self._attr_current_humidity = to_float(data.get("luftfeuchte"))

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        room = find_room(self.coordinator.data, self._floor_id, self._room_id)
        if room is None:
            self._attr_available = False
        else:
            self._attr_available = True
            self._update_from_data(room)
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

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode; only heating is supported."""
        if hvac_mode != HVACMode.HEAT:
            raise HomeAssistantError(f"HVAC mode {hvac_mode} is not supported by Controme")

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
                },
                timeout=REQUEST_TIMEOUT,
            ) as response:
                response_text = await response.text()
        except (ClientError, TimeoutError) as ex:
            raise HomeAssistantError(f"Error communicating with Controme while setting temperature: {ex}") from ex

        if response.status in (401, 403):
            _LOGGER.debug("Auth failed: URL=%s, User=%s, Response=%s",
                        endpoint, self._user, response_text)
            raise HomeAssistantError(
                "Authentication failed when setting temperature. Check your Controme credentials."
            )
        if response.status != 200:
            raise HomeAssistantError(
                f"Error setting temperature: status={response.status}, response={response_text}"
            )

        _LOGGER.debug("Successfully set temperature: %s", response_text)

        # Set local value immediately for responsive UI
        self._attr_target_temperature = temperature
        self.async_write_ha_state()

        # Request a data refresh to update all entities
        await self.coordinator.async_request_refresh()
