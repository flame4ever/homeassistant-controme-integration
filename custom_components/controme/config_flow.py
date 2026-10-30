"""Config flow for Controme integration."""
import logging
from typing import Any, Optional
import voluptuous as vol
import aiohttp
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD, DEFAULT_HAUS_ID
from .helpers import scan_network

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Schema for the initial choice step, option labels come from the translations
STEP_INIT_DATA_SCHEMA = vol.Schema({
    vol.Required("discovery_method"): SelectSelector(
        SelectSelectorConfig(
            options=["auto", "manual"],
            translation_key="discovery_method",
            mode=SelectSelectorMode.LIST,
        )
    ),
})

# Schema for credential entry of a single discovered system
STEP_CREDENTIALS_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USER): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Required(CONF_HAUS_ID, default=DEFAULT_HAUS_ID): str,
})

# Schema for manual entry
STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_API_URL): str,
    vol.Required(CONF_USER): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Required(CONF_HAUS_ID, default=DEFAULT_HAUS_ID): str,
})

class ContromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Controme."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._discovered_systems = []
        self._scan_already_run = False

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            # Reset scan flag when starting a new flow
            self._scan_already_run = False
            # New initial step - ask for discovery method
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_INIT_DATA_SCHEMA,
            )

        # User has made a choice on discovery method
        if user_input["discovery_method"] == "auto":
            # User chose automatic discovery, run it directly
            return await self.async_step_auto_discovery()

        # User chose manual entry
        return await self.async_step_manual_entry()

    async def async_step_auto_discovery(self, user_input: Optional[dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle automatic discovery of Controme systems."""
        # Check if we've already run a scan in this flow
        if self._scan_already_run:
            _LOGGER.warning("Scan already run, using cached results")
            # Use cached results instead of running another scan
            return self._show_form_after_scan()
        
        # Mark that we're running a scan
        self._scan_already_run = True
        
        # Run the scan directly instead of using a progress task
        await self._async_scan_systems()
        
        # Show the appropriate form based on scan results
        return self._show_form_after_scan()

    def _show_form_after_scan(self) -> ConfigFlowResult:
        """Show the appropriate form based on scan results."""
        if self._discovered_systems:
            # If we found exactly one system, go directly to credentials entry
            if len(self._discovered_systems) == 1:
                return self._show_step_form("credentials")
            # If we found multiple systems, show selection screen
            return self._show_step_form("select_system")

        # No systems found, fall back to manual entry
        _LOGGER.warning("No Controme systems found during scan. Falling back to manual entry.")
        return self._show_step_form("manual_entry", {"base": "no_systems_found"})

    def _show_step_form(
        self, step_id: str, errors: Optional[dict[str, str]] = None
    ) -> ConfigFlowResult:
        """Show the form of the given step, optionally with errors."""
        if step_id == "credentials":
            return self.async_show_form(
                step_id="credentials",
                description_placeholders={
                    "system": self._discovered_systems[0]["title"]
                },
                data_schema=STEP_CREDENTIALS_DATA_SCHEMA,
                errors=errors
            )
        if step_id == "select_system":
            return self.async_show_form(
                step_id="select_system",
                description_placeholders={
                    "count": str(len(self._discovered_systems))
                },
                data_schema=vol.Schema({
                    vol.Required(CONF_API_URL): vol.In({
                        system["url"]: system["title"]
                        for system in self._discovered_systems
                    }),
                    vol.Required(CONF_USER): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_HAUS_ID, default=DEFAULT_HAUS_ID): str,
                }),
                errors=errors
            )
        # Manual entry
        return self.async_show_form(
            step_id="manual_entry",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors
        )

    async def _async_scan_systems(self) -> None:
        """Perform the actual network scan."""
        try:
            _LOGGER.info("Starting network scan for Controme systems...")
            # Clear any previous results
            self._discovered_systems = []
            # Run the scan
            self._discovered_systems = await scan_network()
            _LOGGER.info("Network scan complete. Found %d systems", len(self._discovered_systems))
        except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as err:
            _LOGGER.error("Error scanning network: %s", err)
            self._discovered_systems = []

    async def async_step_credentials(self, user_input: Optional[dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle credential entry for a discovered system."""
        if user_input is None:
            # Show the credentials form
            return self._show_step_form("credentials")

        # User has provided credentials
        system = self._discovered_systems[0]
        user_input[CONF_API_URL] = system["url"]

        # Test the connection (the credentials themselves are not checked here)
        return await self._process_user_input(user_input, "credentials")

    async def async_step_manual_entry(self, user_input: Optional[dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle manual entry of Controme system details."""
        if user_input is None:
            # Show the manual entry form directly
            return self._show_step_form("manual_entry")

        # User has provided manual details
        return await self._process_user_input(user_input, "manual_entry")

    async def _process_user_input(
        self, user_input: dict[str, Any], step_id: str
    ) -> ConfigFlowResult:
        """Process the user input of the given step and show it again on errors."""
        errors = {}
        
        base_url = user_input[CONF_API_URL].strip()
        if not base_url.startswith(("http://", "https://")):
            base_url = f"http://{base_url}"
        base_url = base_url.rstrip('/')
        haus_id = str(user_input.get(CONF_HAUS_ID, DEFAULT_HAUS_ID)).strip()

        # Prevent setting up the same house of a Controme system twice
        for entry in self._async_current_entries():
            if (
                entry.data.get(CONF_API_URL, "").rstrip('/').lower() == base_url.lower()
                and str(entry.data.get(CONF_HAUS_ID, DEFAULT_HAUS_ID)) == haus_id
            ):
                return self.async_abort(reason="already_configured")

        try:
            # Test connection with the provided data. The read API does not require
            # authentication, so this only verifies that the system is reachable.
            session = async_get_clientsession(self.hass)
            url = f"{base_url}/get/json/v1/{haus_id}/temps/"

            async with session.get(url, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    errors["base"] = "cannot_connect"
                else:
                    data = await response.json(content_type=None)
                    if not isinstance(data, list):
                        errors["base"] = "cannot_connect"
                    else:
                        # Create config entry
                        return self.async_create_entry(
                            title=f"Controme ({user_input[CONF_API_URL]})",
                            data={
                                CONF_API_URL: base_url,
                                CONF_USER: user_input[CONF_USER],
                                CONF_PASSWORD: user_input[CONF_PASSWORD],
                                CONF_HAUS_ID: haus_id
                            }
                        )
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.error("Error testing connection: %s", err)
            errors["base"] = "cannot_connect"

        # Show the calling step again with the errors
        return self._show_step_form(step_id, errors)

    async def async_step_select_system(self, user_input: Optional[dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle system selection step."""
        if user_input is not None:
            return await self._process_user_input(user_input, "select_system")

        return self._show_step_form("select_system")
