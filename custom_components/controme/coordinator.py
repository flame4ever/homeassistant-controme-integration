"""DataUpdateCoordinator for Controme integration."""
from datetime import timedelta
import logging
from typing import Any, Dict

from aiohttp import ClientError, ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = ClientTimeout(total=10)

type ContromeConfigEntry = ConfigEntry["ContromeDataUpdateCoordinator"]

class ContromeDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching Controme data."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        base_url: str,
        house_id: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )
        self._base_url = base_url
        self._house_id = house_id
        # Device registry ID of the Controme hub, set in async_setup_entry
        self.hub_device_id: str | None = None

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from Controme API."""
        session = async_get_clientsession(self.hass)
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/temps/"

        try:
            start_time = self.hass.loop.time()
            async with session.get(endpoint, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    raise UpdateFailed(f"Error fetching data: {response.status}")
                data = await response.json(content_type=None)
                
            fetch_time = self.hass.loop.time() - start_time
            _LOGGER.debug("Finished fetching controme data in %.3f seconds (success: True)", fetch_time)
            
            # Log a sample of the data for debugging
            if data and isinstance(data, list) and len(data) > 0:
                _LOGGER.debug("Received data for %d floors", len(data))
                # Sample the first floor for debugging
                first_floor = data[0]
                if "raeume" in first_floor and first_floor["raeume"]:
                    sample_room = first_floor["raeume"][0]
                    # Log without sensitive values
                    safe_sample = {k: v for k, v in sample_room.items() 
                                if k not in ["password", "token"]}
                    _LOGGER.debug("Sample room data: %s", safe_sample)
            
        except (ClientError, TimeoutError, ValueError) as err:
            # UpdateFailed is logged by the coordinator itself, so no extra error log here
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        await self._async_add_outputs(session, data)
        return data

    async def _async_add_outputs(self, session, data) -> None:
        """Add the output (valve) values of each room as "ausgang" to the room data.

        The outputs are optional, so errors only leave "ausgang" unset.
        """
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/outs/"
        try:
            async with session.get(endpoint, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    _LOGGER.debug("Could not fetch outputs: %s", response.status)
                    return
                outs = await response.json(content_type=None)
        except (ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("Could not fetch outputs: %s", err)
            return

        if not isinstance(outs, list) or not isinstance(data, list):
            return
        outputs = {
            (floor.get("id"), room.get("id")): room.get("ausgang")
            for floor in outs
            for room in floor.get("raeume") or []
        }
        for floor in data:
            for room in floor.get("raeume") or []:
                ausgang = outputs.get((floor.get("id"), room.get("id")))
                if isinstance(ausgang, dict):
                    room["ausgang"] = ausgang
