"""Config flow for Controme integration with house selection."""
import logging
from typing import Any, Optional
import voluptuous as vol
import aiohttp
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD

_LOGGER = logging.getLogger(__name__)

# Beispielhafter Schema-Entwurf für die Initialisierung
STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_API_URL): str,
    vol.Required(CONF_USER): str,
    vol.Required(CONF_PASSWORD): str,
})

class ContromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Controme."""

    VERSION = 1

    async def async_step_user(self, user_input: Optional[dict[str, Any]] = None) -> FlowResult:
        """Handle the initial step."""
        _LOGGER.info("Starting async_step_user in ContromeConfigFlow")
        _LOGGER.debug("Received parameters: %s", user_input)
        if user_input is not None:
            # Logge die empfangenen Eingaben (ohne das Passwort)
            safe_input = {k: v for k, v in user_input.items() if k != CONF_PASSWORD}
            _LOGGER.debug("Received user input for config flow: %s", safe_input)
            _LOGGER.debug("Proceeding with API probing using base URL: %s", user_input[CONF_API_URL])

            # Hier sicherstellen, dass die API-URL einen http://-Präfix hat
            base_url = user_input[CONF_API_URL].strip()
            if not (base_url.startswith("http://") or base_url.startswith("https://")):
                base_url = f"http://{base_url}"
            base_url = base_url.rstrip("/")
            # API-Probe: Überprüfe mögliche Haus-IDs von 1 bis 9
            houses = []
            async with aiohttp.ClientSession() as session:
                for test_id in range(1, 10):
                    endpoint = f"{base_url}/get/json/v1/{test_id}/temps/"
                    _LOGGER.info("Checking API endpoint for house %s: %s", test_id, endpoint)
                    try:
                        async with session.get(endpoint) as response:
                            _LOGGER.debug("House %s API response status: %s", test_id, response.status)
                            if response.status == 200:
                                data = await response.json()
                                _LOGGER.debug("API response data for house %s: %s", test_id, data)
                                if data:
                                    houses.append({"id": str(test_id), "name": f"House {test_id}"})
                                    _LOGGER.info("Valid house found at ID %s (HTTP 200 with data). Aborting further search.", test_id)
                                    break
                                else:
                                    _LOGGER.debug("House %s API returned empty data", test_id)
                            else:
                                _LOGGER.debug("House %s not valid, response status: %s", test_id, response.status)
                    except Exception as ex:
                        _LOGGER.exception("Exception occurred during API call for house %s: %s", test_id, ex)
            _LOGGER.debug("Completed API probing, valid houses found: %s", houses)

            # Speichere die bisherigen Daten (für weitere Schritte)
            self._user_input = user_input.copy()
            _LOGGER.debug("User input stored for further steps: %s", {k: v for k, v in self._user_input.items() if k != CONF_PASSWORD})

            # Logik zur Auswahl des Hauses basierend auf den validen Test-IDs
            if not houses:
                _LOGGER.error("No houses found via the API.")
                return self.async_show_form(
                    step_id="user",
                    data_schema=STEP_USER_DATA_SCHEMA,
                    errors={"base": "cannot_connect"},
                )
            elif len(houses) == 1:
                house = houses[0]
                self._user_input[CONF_HAUS_ID] = house.get("id")
                _LOGGER.info("One house found, auto-selecting house: %s", house.get("id"))
                _LOGGER.debug("Creating config entry with data: %s", self._user_input)
                return self.async_create_entry(title="Controme", data=self._user_input)
            else:
                # Bei mehreren gefundenen Häusern: Speichere die Liste und wechsle in den Auswahl-Schritt.
                self.houses = houses
                _LOGGER.info("Multiple houses found: %s", houses)
                _LOGGER.debug("Presenting selection form for multiple houses")
                return self.async_show_form(
                    step_id="select_house",
                    data_schema=vol.Schema({
                        vol.Required(CONF_HAUS_ID): vol.In({
                            house["id"]: house.get("name", house["id"]) for house in houses
                        })
                    })
                )

        _LOGGER.debug("No user input provided, showing form with schema: %s", STEP_USER_DATA_SCHEMA)
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
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
            return self.async_show_form(step_id="select_house", data_schema=data_schema)

        _LOGGER.info("House selected: %s", user_input[CONF_HAUS_ID])
        self._user_input[CONF_HAUS_ID] = user_input[CONF_HAUS_ID]
        _LOGGER.debug("Final user input data for config entry: %s", self._user_input)
        _LOGGER.info("Creating config entry for Controme integration based on selected house")
        return self.async_create_entry(title="Controme", data=self._user_input)