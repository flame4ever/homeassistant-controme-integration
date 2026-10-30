"""Support for the Controme transmission problem binary sensor."""
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant

from .coordinator import ContromeConfigEntry
from .entity import ContromeTransmissionEntity

# The binary sensor only reads coordinator data, so updates need no limit
PARALLEL_UPDATES = 0

async def async_setup_entry(hass: HomeAssistant, entry: ContromeConfigEntry, async_add_entities):
    """Set up the Controme binary sensor platform."""
    async_add_entities([ContromeTransmissionProblemBinarySensor(entry.runtime_data, entry)])

class ContromeTransmissionProblemBinarySensor(ContromeTransmissionEntity, BinarySensorEntity):
    """On if at least one Controme sensor has not transmitted within the threshold."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    # The list changes often and can be long, keep it out of the recorder database
    _unrecorded_attributes = frozenset({"stale_sensors"})

    def __init__(self, coordinator, config_entry):
        """Initialize the binary sensor on the hub device."""
        super().__init__(coordinator, config_entry, "transmission_problem")

    @property
    def is_on(self) -> bool:
        """Return True if at least one sensor is stale."""
        return self._stale_count > 0

    @property
    def extra_state_attributes(self):
        """Return the threshold and the (at most 20) oldest stale sensors."""
        return {
            "threshold_minutes": self._threshold_minutes,
            "stale_sensors": self._stale,
        }
