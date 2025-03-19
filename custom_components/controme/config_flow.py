"""Config flow for Controme integration."""
import logging
from typing import Any, Optional
import voluptuous as vol
import aiohttp
import asyncio
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD
from .helpers import scan_network

_LOGGER = logging.getLogger(__name__)

# Schema for the initial choice step - using direct texts for options
STEP_INIT_DATA_SCHEMA = vol.Schema({
    vol.Required("discovery_method"): vol.In({
        "auto": "Automatisch nach Controme-Systemen im Netzwerk suchen",
        "manual": "IP-Adresse und Zugangsdaten manuell eingeben"
    }),
})

# Schema for manual entry
STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_API_URL): str,
    vol.Required(CONF_USER): str,
    vol.Required(CONF_PASSWORD): str,
})

class ContromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Controme."""

    VERSION = 1

    def __init__(self):
        """Initialize the config flow."""
        self._discovered_systems = []
        self._user_input = {}
        self._scan_already_run = False

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            # Reset scan flag when starting a new flow
            self._scan_already_run = False
            # New initial step - ask for discovery method
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_INIT_DATA_SCHEMA,
                description_placeholders={"title": "Controme Einrichtung"},
            )
        
        # User has made a choice on discovery method
        if "discovery_method" in user_input:
            discovery_method = user_input["discovery_method"]
            
            if discovery_method == "auto":
                # User chose automatic discovery, run it directly
                return await self.async_step_auto_discovery()
            else:
                # User chose manual entry
                return await self.async_step_manual_entry()

        # If we get here, we're handling manual entry with data already provided
        return await self._process_user_input(user_input)

    async def async_step_auto_discovery(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
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

    def _show_form_after_scan(self) -> FlowResult:
        """Show the appropriate form based on scan results."""
        if self._discovered_systems:
            # If we found exactly one system, go directly to credentials entry
            if len(self._discovered_systems) == 1:
                system = self._discovered_systems[0]
                return self.async_show_form(
                    step_id="credentials",
                    description_placeholders={
                        "system": system["title"]
                    },
                    data_schema=vol.Schema({
                        vol.Required(CONF_USER): str,
                        vol.Required(CONF_PASSWORD): str,
                    })
                )
            # If we found multiple systems, show selection screen
            else:
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
                    })
                )
        
        # No systems found, fall back to manual entry
        _LOGGER.warning("No Controme systems found during scan. Falling back to manual entry.")
        return self.async_show_form(
            step_id="manual_entry",
            description_placeholders={
                "error": "No systems found automatically. Please enter details manually."
            },
            data_schema=STEP_USER_DATA_SCHEMA
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
        except Exception as err:
            _LOGGER.error("Error scanning network: %s", err)
            self._discovered_systems = []

    async def async_step_credentials(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle credential entry for a discovered system."""
        errors = {}
        
        if user_input is None:
            # Show the credentials form
            return self.async_show_form(
                step_id="credentials",
                description_placeholders={
                    "system": self._discovered_systems[0]["title"]
                },
                data_schema=vol.Schema({
                    vol.Required(CONF_USER): str,
                    vol.Required(CONF_PASSWORD): str,
                }),
                errors=errors
            )
        
        # User has provided credentials
        system = self._discovered_systems[0]
        user_input[CONF_API_URL] = system["url"]
        
        # Test the connection with the provided credentials
        return await self._process_user_input(user_input)

    async def async_step_manual_entry(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle manual entry of Controme system details."""
        errors = {}
        
        if user_input is None:
            # Show the manual entry form directly
            return self.async_show_form(
                step_id="manual_entry",
                data_schema=STEP_USER_DATA_SCHEMA,
                errors=errors
            )
        
        # User has provided manual details
        return await self._process_user_input(user_input)

    async def _process_user_input(self, user_input: dict[str, Any]) -> FlowResult:
        """Process the user input from either discovery or manual entry."""
        errors = {}
        
        try:
            # Test connection with the provided data
            async with aiohttp.ClientSession() as session:
                base_url = user_input[CONF_API_URL]
                if not base_url.startswith(("http://", "https://")):
                    base_url = f"http://{base_url}"
                url = f"{base_url.rstrip('/')}/get/json/v1/1/temps/"
                
                async with session.get(
                    url,
                    auth=aiohttp.BasicAuth(user_input[CONF_USER], user_input[CONF_PASSWORD])
                ) as response:
                    if response.status == 401:
                        errors["base"] = "invalid_auth"
                    elif response.status != 200:
                        errors["base"] = "cannot_connect"
                    else:
                        # Save inputs for later steps
                        self._user_input = user_input
                        # Create config entry
                        return self.async_create_entry(
                            title=f"Controme ({user_input[CONF_API_URL]})",
                            data={
                                CONF_API_URL: base_url,
                                CONF_USER: user_input[CONF_USER],
                                CONF_PASSWORD: user_input[CONF_PASSWORD],
                                CONF_HAUS_ID: "1"  # Default house ID
                            }
                        )
        except Exception as err:
            _LOGGER.error("Error testing connection: %s", err)
            errors["base"] = "cannot_connect"

        # Show form again on errors
        if "discovery_method" in user_input:
            # We were on the initial step
            return self.async_show_form(
                step_id="user",
                data_schema=STEP_INIT_DATA_SCHEMA,
                errors=errors
            )
        elif CONF_API_URL in user_input and user_input[CONF_API_URL] in [system["url"] for system in self._discovered_systems]:
            # We were on the system selection step
            return self.async_show_form(
                step_id="select_system",
                data_schema=vol.Schema({
                    vol.Required(CONF_API_URL): vol.In({
                        system["url"]: system["title"] 
                        for system in self._discovered_systems
                    }),
                    vol.Required(CONF_USER): str,
                    vol.Required(CONF_PASSWORD): str,
                }),
                errors=errors
            )
        elif len(self._discovered_systems) == 1:
            # We were on the credentials step for a single discovered system
            return self.async_show_form(
                step_id="credentials",
                description_placeholders={
                    "system": self._discovered_systems[0]["title"]
                },
                data_schema=vol.Schema({
                    vol.Required(CONF_USER): str,
                    vol.Required(CONF_PASSWORD): str,
                }),
                errors=errors
            )
        else:
            # We were on the manual entry step
            return self.async_show_form(
                step_id="manual_entry",
                data_schema=STEP_USER_DATA_SCHEMA,
                errors=errors
            )

    async def async_step_select_system(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle system selection step."""
        if user_input is not None:
            return await self._process_user_input(user_input)

        return self.async_show_form(
            step_id="select_system",
            data_schema=vol.Schema({
                vol.Required(CONF_API_URL): vol.In({
                    system["url"]: system["title"] 
                    for system in self._discovered_systems
                }),
                vol.Required(CONF_USER): str,
                vol.Required(CONF_PASSWORD): str,
            })
        )

    async def async_step_select_house(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle the house selection step when multiple houses are found."""
        if user_input is None:
            _LOGGER.debug("Entered async_step_select_house without user input. Available houses: %s", self.houses)
            data_schema = vol.Schema({
                vol.Required(CONF_HAUS_ID): vol.In({
                    house["id"]: house.get("name", house["id"]) for house in self.houses
                })
            })
            _LOGGER.debug("Showing select_house form with schema: %s", data_schema)
            return self.async_show_form(
                step_id="select_house", 
                data_schema=data_schema
            )

        _LOGGER.info("House selected: %s", user_input[CONF_HAUS_ID])
        self._user_input[CONF_HAUS_ID] = user_input[CONF_HAUS_ID]
        _LOGGER.debug("Final user input data for config entry: %s", self._user_input)
        _LOGGER.info("Creating config entry for Controme integration based on selected house")
        return self.async_create_entry(title="Controme", data=self._user_input)
        
    # Tell Home Assistant how to handle the progress screen
    @staticmethod
    def async_get_progress_steps() -> list[str]:
        """Return a list of steps that are shown while we're in progress."""
        return ["auto_discovery"]