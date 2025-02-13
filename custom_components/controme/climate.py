"""Platform for climate integration."""
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
        haus_id = config.get('haus_id', 'unknown')
        self._attr_unique_id = f"controme_{haus_id}"
        self._attr_name = f"Controme {haus_id}"
        self._current_temperature: Optional[float] = None
        self._target_temperature: Optional[float] = None
        self._hvac_mode: HVACMode = HVACMode.OFF

    @property
    def current_temperature(self) -> Optional[float]:
        """Return the current temperature of the thermostat."""
        return self._current_temperature

    @property
    def target_temperature(self) -> Optional[float]:
        """Return the target temperature."""
        return self._target_temperature

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode."""
        return self._hvac_mode

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            # Hier kann die API angesprochen werden, um die Temperatur zu ändern.
            self._target_temperature = temperature
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        # Hier kann die API angesprochen werden, um den Modus zu ändern.
        self._hvac_mode = hvac_mode
        self.async_write_ha_state()