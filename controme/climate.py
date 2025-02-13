"""Platform for climate integration."""
from typing import Any
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
    async_add_entities([ContromeThermostat(entry.data)])

class ContromeThermostat(ClimateEntity):
    """Representation of a Controme Thermostat."""

    _attr_has_entity_name = True
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_should_poll = False

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the Controme thermostat."""
        self._config = config
        self._attr_unique_id = f"controme_{config['haus_id']}"
        self._attr_name = f"Controme {config['haus_id']}"
        self._current_temperature: float | None = None
        self._target_temperature: float | None = None
        self._hvac_mode: HVACMode = HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature of the thermostat."""
        return self._current_temperature

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._target_temperature

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            # Hier können Sie die API ansprechen, um die Temperatur zu ändern.
            self._target_temperature = temperature
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        # Hier können Sie die API ansprechen, um den Modus zu ändern.
        self._hvac_mode = hvac_mode
        self.async_write_ha_state() 