"""Support for Controme climate devices."""
import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import async_get_json, async_post, room_read_url, room_write_url
from .coordinator import ContromeConfigEntry
from .helpers import find_room, find_room_by_id, is_synthetic_room, iter_rooms, to_float
from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)
# Send temperature changes to the Controme system one at a time
PARALLEL_UPDATES = 1

# Controme documents "heating", "cooling", "off" and "on"; some firmwares report
# capitalized strings ("Heating") or integers (0 = off, 1 = cooling, 2 = heating).
# The integer mapping comes from issue #22 and is not documented by Controme.
BETRIEBSART_TO_HVAC_MODE = {
    "heating": HVACMode.HEAT,
    "on": HVACMode.HEAT,
    "cooling": HVACMode.COOL,
    "off": HVACMode.OFF,
    0: HVACMode.OFF,
    1: HVACMode.COOL,
    2: HVACMode.HEAT,
}

# Modes that can be written; "cooling" and "on" are never sent
HVAC_MODE_TO_BETRIEBSART = {
    HVACMode.HEAT: "heating",
    HVACMode.OFF: "off",
}
# Seconds after the POST at which the room is read back (#22: values read back
# immediately can still show the old mode)
READBACK_DELAYS = (2, 5, 10)

def betriebsart_to_hvac_mode(betriebsart: Any) -> HVACMode:
    """Map a Controme betriebsart to an HVAC mode, defaulting to heating."""
    if isinstance(betriebsart, str):
        betriebsart = betriebsart.strip().lower()
        # Digit strings ("0", "1", "2") are treated like the integer values
        if betriebsart.isascii() and betriebsart.isdigit():
            betriebsart = int(betriebsart)
    # bool is a subclass of int, so True/False must not match 1/0; other types
    # (e.g. lists) are not hashable and cannot be looked up
    if isinstance(betriebsart, (str, int)) and not isinstance(betriebsart, bool):
        hvac_mode = BETRIEBSART_TO_HVAC_MODE.get(betriebsart)
        if hvac_mode is not None:
            return hvac_mode
    _LOGGER.debug("Unknown betriebsart %r, using heating", betriebsart)
    return HVACMode.HEAT

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
            model="Room",
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

    _attr_has_entity_name = True
    # The entity takes the name of its room device
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5
    _attr_min_temp = 5
    _attr_max_temp = 30
    # Heating and off can be switched, a different reported mode is added in _update_from_data
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_hvac_mode = HVACMode.HEAT
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE

    def __init__(self, coordinator, config_entry, room_data, device_info):
        """Initialize the climate device."""
        super().__init__(coordinator)
        self._base_url = config_entry.data[CONF_API_URL].rstrip('/')
        self._device_info = device_info
        self._room_id = room_data.get("room_id", room_data.get("id"))
        room_name = room_data.get("name") or f"Room {self._room_id}"
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        self._user = config_entry.data[CONF_USER]
        self._password = config_entry.data[CONF_PASSWORD]
        self._attr_unique_id = f"{config_entry.data[CONF_HAUS_ID]}_{self._floor_id}_{self._room_id}_climate"
        self.entity_id = f"climate.controme_{slugify(room_name)}"
        # Floors without rooms and rooms without ID have no real room ID to send to
        self._synthetic_room = is_synthetic_room(coordinator.data, room_data)
        self._room_present = True
        self._update_from_data(room_data)

    def _update_from_data(self, data):
        """Update attrs from data."""
        self._attr_current_temperature = to_float(data.get("temperatur"))
        self._attr_target_temperature = to_float(data.get("solltemperatur"))
        self._attr_current_humidity = to_float(data.get("luftfeuchte"))
        self._attr_hvac_mode = betriebsart_to_hvac_mode(data.get("betriebsart"))
        # Heating and off can be selected; a reported mode like cooling is shown, but not sent
        self._attr_hvac_modes = list(HVAC_MODE_TO_BETRIEBSART)
        if self._attr_hvac_mode not in self._attr_hvac_modes:
            self._attr_hvac_modes.append(self._attr_hvac_mode)
        self._attr_hvac_action = self._hvac_action_from_outputs(data.get("ausgang"))

    def _hvac_action_from_outputs(self, ausgang: Any) -> HVACAction | None:
        """Derive the HVAC action from the room's output (valve) values."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        values = [to_float(value) for value in ausgang.values()] if isinstance(ausgang, dict) else []
        values = [value for value in values if value is not None]
        # Rooms without outputs (or without output data) have no known action
        if not values:
            return None
        if any(value > 0 for value in values):
            return HVACAction.COOLING if self._attr_hvac_mode == HVACMode.COOL else HVACAction.HEATING
        return HVACAction.IDLE

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        room = find_room(self.coordinator.data, self._floor_id, self._room_id)
        if room is None:
            self._room_present = False
        else:
            self._room_present = True
            self._update_from_data(room)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return if the coordinator is up and the room is still reported."""
        # CoordinatorEntity.available only reflects the last coordinator update
        return super().available and self._room_present

    @property
    def device_info(self):
        """Return device info."""
        return self._device_info

    async def _async_write(self, endpoint: str, data: dict[str, Any]) -> str:
        """Send a write request for this room via the central API helper."""
        return await async_post(self.hass, endpoint, data, self._user, self._password)

    def _check_real_room(self) -> None:
        """Raise ServiceValidationError for floors without rooms and rooms without ID."""
        if self._synthetic_room:
            raise ServiceValidationError(
                f"Room ID {self._room_id} is not a real Controme room, the target "
                "temperature can only be set for rooms with their own room ID"
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Switch the Controme betriebsart of this room to heating or off."""
        self._check_real_room()
        betriebsart = HVAC_MODE_TO_BETRIEBSART.get(hvac_mode)
        if betriebsart is None:
            # e.g. cooling, which is shown when reported but never sent
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unsupported_hvac_mode",
                translation_placeholders={"mode": str(hvac_mode)},
            )

        await self._async_write(
            room_write_url(self._base_url, self._house_id, "rooms", self._room_id),
            {"action": "betriebsart", "value": betriebsart},
        )

        # Show the new mode until the read back confirms or contradicts it
        self._attr_hvac_mode = hvac_mode
        self._attr_hvac_action = HVACAction.OFF if hvac_mode == HVACMode.OFF else None
        self.async_write_ha_state()

        applied, reported = await self._async_read_back_mode(hvac_mode)
        await self.coordinator.async_request_refresh()
        if not applied:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="mode_not_applied",
                translation_placeholders={"mode": str(hvac_mode), "value": str(reported)},
            )

    async def _async_read_back_mode(self, hvac_mode: HVACMode) -> tuple[bool, Any]:
        """Read the room back after the POST; return (applied, reported betriebsart).

        If the room cannot be read at all, the mode counts as applied, the
        coordinator refresh shows the actual state.
        """
        url = room_read_url(self._base_url, self._house_id, self._room_id)
        waited = 0
        reported = None
        read_any = False
        for delay in READBACK_DELAYS:
            await asyncio.sleep(delay - waited)
            waited = delay
            room = find_room_by_id(await async_get_json(self.hass, url), self._room_id)
            if room is None:
                continue
            read_any = True
            reported = room.get("betriebsart")
            if betriebsart_to_hvac_mode(reported) == hvac_mode:
                return True, reported
        if read_any:
            _LOGGER.debug("Room %s reports betriebsart %r after setting %s",
                          self._room_id, reported, hvac_mode)
        return not read_any, reported

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return

        self._check_real_room()

        await self._async_write(
            room_write_url(self._base_url, self._house_id, "soll", self._room_id),
            {"soll": str(float(temperature))},
        )

        # Set local value immediately for responsive UI
        self._attr_target_temperature = temperature
        self.async_write_ha_state()

        # Request a data refresh to update all entities
        await self.coordinator.async_request_refresh()
