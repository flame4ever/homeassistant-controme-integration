"""DataUpdateCoordinator for Controme integration."""
from datetime import timedelta
import logging
from typing import Any, Dict

from aiohttp import ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = ClientTimeout(total=10)

class ContromeDataUpdateCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    """Class to manage fetching Controme data."""

    def __init__(
        self,
        hass: HomeAssistant,
        base_url: str,
        house_id: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=60),
        )
        self._base_url = base_url
        self._house_id = house_id

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from Controme API."""
        session = async_get_clientsession(self.hass)
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/temps/"

        try:
            start_time = self.hass.loop.time()
            async with session.get(endpoint, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    raise UpdateFailed(f"Error fetching data: {response.status}")
                data = await response.json()
                
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
            
            return data
        except Exception as ex:
            _LOGGER.error("Error communicating with API: %s", str(ex))
            raise UpdateFailed(f"Error communicating with API: {str(ex)}") 