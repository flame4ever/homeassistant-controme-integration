"""Support for Controme climate devices."""
import json
import logging
import math
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
from homeassistant.helpers import service
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .api import (
    async_get_json,
    async_post,
    room_write_url,
    scene_write_url,
    scenes_read_url,
)
from .coordinator import ContromeConfigEntry
from .helpers import (
    check_scene_for_room,
    find_room,
    is_synthetic_room,
    iter_rooms,
    parse_mode_end,
    room_labels,
    to_float,
)
from .const import (
    DOMAIN,
    CONF_API_URL,
    CONF_HAUS_ID,
    CONF_USER,
    CONF_PASSWORD,
    MIN_TEMPERATURE,
    MAX_TEMPERATURE,
    TEMPERATURE_STEP,
)

_LOGGER = logging.getLogger(__name__)
# Send temperature changes to the Controme system one at a time
PARALLEL_UPDATES = 1
# Controme reports a temporary temperature only after some seconds, refresh afterwards
DELAYED_REFRESH_SECONDS = 10

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

def temporary_mode(value: Any) -> bool:
    """Interpret "is_temporary_mode" (bool, or strings like "true"/"false")."""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)

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
    _attr_target_temperature_step = TEMPERATURE_STEP
    _attr_min_temp = MIN_TEMPERATURE
    _attr_max_temp = MAX_TEMPERATURE
    # The mode follows the Controme betriebsart, switching it is not implemented
    _attr_hvac_modes = [HVACMode.HEAT]
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
        self._entry_id = config_entry.entry_id
        self._attr_unique_id = f"{config_entry.data[CONF_HAUS_ID]}_{self._floor_id}_{self._room_id}_climate"
        self.entity_id = f"climate.controme_{slugify(room_name)}"
        # Floors without rooms and rooms without ID have no real room ID to send to
        self._synthetic_room = is_synthetic_room(coordinator.data, room_data)
        self._room_present = True
        self._unsub_delayed_refresh = None
        self._update_from_data(room_data)

    def _update_from_data(self, data):
        """Update attrs from data."""
        self._attr_current_temperature = to_float(data.get("temperatur"))
        self._attr_target_temperature = to_float(data.get("solltemperatur"))
        self._attr_current_humidity = to_float(data.get("luftfeuchte"))
        # Only the current mode is offered, as it cannot be switched from Home Assistant
        self._attr_hvac_mode = betriebsart_to_hvac_mode(data.get("betriebsart"))
        self._attr_hvac_modes = [self._attr_hvac_mode]
        self._attr_hvac_action = self._hvac_action_from_outputs(data.get("ausgang"))
        self._temporary_attributes = self._temporary_attributes_from_data(data)

    @staticmethod
    def _temporary_attributes_from_data(data) -> dict[str, Any]:
        """Return the temporary mode attributes, only for fields /temps/ actually reports."""
        attributes = {}
        if "is_temporary_mode" in data:
            attributes["temporary_mode"] = temporary_mode(data["is_temporary_mode"])
        if "mode_end_datetime" in data:
            attributes["temporary_until"] = parse_mode_end(data["mode_end_datetime"])
        if "perm_solltemperatur" in data:
            attributes["permanent_target_temperature"] = to_float(data["perm_solltemperatur"])
        return attributes

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

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the temporary mode attributes if Controme reports them."""
        return self._temporary_attributes

    async def _async_write(self, endpoint: str, data: dict[str, Any]) -> str:
        """Send a write request for this room via the central API helper."""
        return await async_post(self.hass, self._base_url, endpoint, data, self._user, self._password)

    def _check_real_room(self) -> None:
        """Raise ServiceValidationError for floors without rooms and rooms without ID."""
        if self._synthetic_room:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_a_room",
                translation_placeholders={"room_id": str(self._room_id)},
            )

    def _check_entry_loaded(self) -> None:
        """Raise a translated ServiceValidationError unless the config entry is loaded."""
        service.async_get_config_entry(self.hass, DOMAIN, self._entry_id)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Reject mode changes, the betriebsart can only be changed in Controme.

        The firmware rejects the documented betriebsart write (HTTP 400), so
        nothing is sent; selecting the current mode does nothing.
        """
        if hvac_mode != self._attr_hvac_mode:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="hvac_mode_not_supported",
                translation_placeholders={"mode": str(hvac_mode)},
            )

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

    async def async_set_temporary_temperature(
        self, temperature: float, duration: int | None = None
    ) -> None:
        """Set a temporary target temperature (service controme.set_temporary_temperature).

        Without a duration Controme uses its default duration ("default").
        """
        self._check_entry_loaded()
        self._check_real_room()
        await self._async_write(
            room_write_url(self._base_url, self._house_id, "ziel", self._room_id),
            {
                "ziel": str(float(temperature)),
                "duration": "default" if duration is None else str(duration),
            },
        )

        # Show the value right away; Controme reports it only after a few seconds,
        # an immediate refresh would jump back to the old value
        self._attr_target_temperature = temperature
        self.async_write_ha_state()
        self._schedule_delayed_refresh()

    async def async_reset_temporary_temperature(self) -> None:
        """End a temporary temperature (service controme.reset_temporary_temperature).

        Controme has no reset call; a normal soll write ends the temporary value.
        The permanent target temperature reported by Controme ("perm_solltemperatur")
        is sent again, so the permanent value itself does not change. Without it
        nothing is sent.
        """
        self._check_entry_loaded()
        self._check_real_room()
        room = find_room(self.coordinator.data, self._floor_id, self._room_id) or {}
        if "is_temporary_mode" in room and not temporary_mode(room["is_temporary_mode"]):
            _LOGGER.debug("Room %s has no temporary temperature, nothing to reset", self._room_id)
            return
        permanent = to_float(room.get("perm_solltemperatur"))
        if permanent is None or not math.isfinite(permanent):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="temporary_reset_unavailable",
                translation_placeholders={"room_id": str(self._room_id)},
            )

        await self._async_write(
            room_write_url(self._base_url, self._house_id, "soll", self._room_id),
            {"soll": str(permanent)},
        )
        # Controme reports the end of the temporary value only after some seconds
        self._attr_target_temperature = permanent
        self.async_write_ha_state()
        self._schedule_delayed_refresh()

    async def async_activate_scene(self, scene_id: int, duration: int | None = None) -> None:
        """Activate a Controme scene for this room (service controme.activate_scene).

        Only scenes that list exactly this room are sent, with room_id of this
        room; without a duration the scene stays active until the next switch.
        """
        self._check_entry_loaded()
        self._check_real_room()

        scenes = await async_get_json(self.hass, scenes_read_url(self._base_url, self._house_id))
        labels = room_labels(self.coordinator.data)
        target_label = next(
            (label for floor_id, room_id, label in labels
             if floor_id == self._floor_id and room_id == self._room_id),
            "",
        )
        problem = check_scene_for_room(scenes, scene_id, target_label, [label for _f, _r, label in labels])
        if problem is not None:
            key, placeholders = problem
            _LOGGER.debug("Scene %s not sent for room %s: %s", scene_id, self._room_id, key)
            # An unreadable scene list is a Controme problem, not a wrong user input
            if key == "scene_list_unavailable":
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key=key)
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=key,
                translation_placeholders=placeholders,
            )

        scene_data = {"room_id": str(self._room_id)}
        if duration is not None:
            scene_data["duration"] = str(duration)
        response_text = await self._async_write(
            scene_write_url(self._base_url, self._house_id, scene_id), scene_data
        )
        self._schedule_delayed_refresh()
        self._check_scene_roomlist(scene_id, response_text, labels)

    def _check_scene_roomlist(self, scene_id: int, response_text: str, labels: list) -> None:
        """Raise if the scene response lists other rooms than this one.

        Controme answers with {"roomlist": {"<room id>": <temperature>, ...}, "time": ...};
        a missing or unreadable roomlist is only logged.
        """
        try:
            roomlist = json.loads(response_text).get("roomlist")
        except (ValueError, AttributeError):
            roomlist = None
        if not isinstance(roomlist, dict):
            _LOGGER.debug("Scene %s: no readable roomlist in the response", scene_id)
            return
        other_ids = [room_id for room_id in roomlist if str(room_id) != str(self._room_id)]
        if not other_ids:
            return
        names = {str(room_id): label for _floor_id, room_id, label in labels}
        other_rooms = ", ".join(names.get(str(room_id), f"Room {room_id}") for room_id in other_ids)
        _LOGGER.warning("Controme scene %s was applied to other rooms than %s: %s",
                        scene_id, self._room_id, other_rooms)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="scene_applied_to_other_rooms",
            translation_placeholders={"scene_id": str(scene_id), "rooms": other_rooms},
        )

    def _schedule_delayed_refresh(self) -> None:
        """Refresh the coordinator after DELAYED_REFRESH_SECONDS, replacing a pending refresh."""
        self._cancel_delayed_refresh()
        self._unsub_delayed_refresh = async_call_later(
            self.hass, DELAYED_REFRESH_SECONDS, self._async_delayed_refresh
        )

    async def _async_delayed_refresh(self, _now) -> None:
        """Refresh the coordinator data after a write."""
        self._unsub_delayed_refresh = None
        await self.coordinator.async_request_refresh()

    def _cancel_delayed_refresh(self) -> None:
        """Cancel a pending delayed refresh."""
        if self._unsub_delayed_refresh is not None:
            self._unsub_delayed_refresh()
            self._unsub_delayed_refresh = None

    async def async_added_to_hass(self) -> None:
        """Register the cancellation of a pending delayed refresh for removal/unload."""
        await super().async_added_to_hass()
        self.async_on_remove(self._cancel_delayed_refresh)
