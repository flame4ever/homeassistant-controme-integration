"""Config flow for Controme integration with house selection."""
from typing import Any
import voluptuous as vol
import aiohttp
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD

class ContromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Controme integration including house selection."""
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._user_input: dict[str, Any] = {}
        self._houses: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 1: Collect API URL, username, and password."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # URL-Validierung: Muss mit "http://" oder "https://" beginnen
            if not user_input[CONF_API_URL].startswith(("http://", "https://")):
                errors[CONF_API_URL] = "invalid_url_format"
            else:
                # Eingaben speichern
                self._user_input = user_input.copy()

                # Versuche, die verfügbaren Haus-IDs über die API abzurufen
                houses = await self._fetch_house_ids(user_input)
                if not houses:
                    errors["base"] = "cannot_connect"
                elif len(houses) == 1:
                    # Nur eine Haus-ID gefunden, diese dann automatisch verwenden.
                    haus_id = houses[0].get(CONF_HAUS_ID)
                    self._user_input[CONF_HAUS_ID] = haus_id
                    unique_id = f"{user_input[CONF_API_URL]}_{haus_id}"
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Controme {haus_id}",
                        data=self._user_input,
                    )
                else:
                    # Mehrere Haus-IDs gefunden – speichere die Liste und wechsle in den Auswahl-Schritt.
                    self._houses = houses
                    return await self.async_step_select_house()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_URL, description={"suggested_value": "http://"}) : str,
                vol.Required(CONF_USER): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )

    async def async_step_select_house(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Step 2: Auswählen der Haus-ID, wenn mehrere vorhanden sind."""
        if user_input is None:
            # Erstelle Auswahlmöglichkeiten aus der abgerufenen Hausliste.
            house_options = {
                str(house.get(CONF_HAUS_ID)): f"{house.get('name', 'Haus ' + str(house.get(CONF_HAUS_ID)))}"
                for house in self._houses
            }
            return self.async_show_form(
                step_id="select_house",
                data_schema=vol.Schema({
                    vol.Required(CONF_HAUS_ID): vol.In(house_options)
                }),
                errors={},
            )
        else:
            # Der Benutzer hat eine Haus-ID ausgewählt.
            haus_id = int(user_input[CONF_HAUS_ID])
            self._user_input[CONF_HAUS_ID] = haus_id
            unique_id = f"{self._user_input[CONF_API_URL]}_{haus_id}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Controme {haus_id}",
                data=self._user_input,
            )

    async def _fetch_house_ids(self, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Holt die verfügbaren Haus-IDs von der Controme API.

        Erwartetes API-Endpoint: {api_url}/houses

        Rückgabewert:
          Eine Liste von Dictionaries, z. B.:
            [{"haus_id": 123, "name": "Hauptwohnsitz"}, {"haus_id": 456, "name": "Ferienhaus"}]
          Bei Verbindungsproblemen wird eine leere Liste zurückgegeben.
        """
        api_url = config[CONF_API_URL].rstrip("/")
        endpoint = f"{api_url}/houses"
        auth = aiohttp.BasicAuth(config[CONF_USER], config[CONF_PASSWORD])
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, auth=auth, timeout=10) as response:
                    if response.status != 200:
                        return []
                    data = await response.json()
                    # Sicherstellen, dass jedes Element einen Schlüssel für die Haus-ID enthält.
                    houses = []
                    for item in data:
                        if CONF_HAUS_ID in item:
                            houses.append(item)
                        elif "haus_id" in item:
                            item[CONF_HAUS_ID] = item.get("haus_id")
                            houses.append(item)
                    return houses
        except Exception:
            return [] 