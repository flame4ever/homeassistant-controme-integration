"""Base entity for the Controme transmission monitoring on the hub device."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    CONF_HAUS_ID,
    CONF_STALE_THRESHOLD,
    DEFAULT_STALE_THRESHOLD,
    MIN_STALE_THRESHOLD,
    MAX_STALE_THRESHOLD,
)
from .helpers import collect_stale

# The age of the transmissions grows without new data, so it is recalculated every minute
RECALCULATE_INTERVAL = timedelta(minutes=1)

def stale_threshold_minutes(options) -> int:
    """Return the stale threshold option, raising stored values below the minimum (no migration)."""
    threshold = int(options.get(CONF_STALE_THRESHOLD, DEFAULT_STALE_THRESHOLD))
    return min(max(threshold, MIN_STALE_THRESHOLD), MAX_STALE_THRESHOLD)

class ContromeTransmissionEntity(CoordinatorEntity):
    """Hub entity derived from the last transmissions of all Controme sensors."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Entity platform of the subclass ("sensor" or "binary_sensor"), used for the entity ID
    _platform_domain: str

    def __init__(self, coordinator, config_entry, key: str) -> None:
        """Initialize the entity on the existing hub device (DOMAIN, haus_id)."""
        super().__init__(coordinator)
        house_id = config_entry.data[CONF_HAUS_ID]
        self._attr_unique_id = f"{house_id}_{key}"
        # Fixed, language independent entity ID like the other Controme entities
        self.entity_id = f"{self._platform_domain}.controme_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, house_id)})
        self._threshold_minutes = stale_threshold_minutes(config_entry.options)
        self._has_data = False
        self._newest: Optional[datetime] = None
        self._stale_count = 0
        self._stale: List[Dict[str, Any]] = []
        self._recalculate(dt_util.utcnow())

    @property
    def available(self) -> bool:
        """Return True once data was received, also while polling fails."""
        # CoordinatorEntity.available would only reflect the last coordinator update;
        # the last known transmissions keep aging instead, so a failure turns stale
        return self._has_data

    async def async_added_to_hass(self) -> None:
        """Start recalculating the transmission age every minute."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_recalculate, RECALCULATE_INTERVAL)
        )

    @callback
    def _async_recalculate(self, now: datetime) -> None:
        """Recalculate the stale sensors with the current time."""
        self._recalculate(now)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._recalculate(dt_util.utcnow())
        self.async_write_ha_state()

    def _recalculate(self, now: datetime) -> None:
        """Update the newest transmission and the stale sensors from the coordinator data."""
        # The coordinator keeps its last data when an update fails
        if self.coordinator.data is None:
            return
        self._has_data = True
        self._newest, self._stale_count, self._stale = collect_stale(
            self.coordinator.data, now, timedelta(minutes=self._threshold_minutes)
        )
