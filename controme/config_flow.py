"""Config flow for Controme integration."""
from typing import Any
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, CONF_USER, CONF_PASSWORD

class ContromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Controme."""
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # URL-Validierung: Muss mit "http://" oder "https://" beginnen
            if not user_input[CONF_API_URL].startswith(("http://", "https://")):
                errors[CONF_API_URL] = "invalid_url_format"
            else:
                unique_id = f"{user_input[CONF_API_URL]}_{user_input[CONF_HAUS_ID]}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Versuchen, die Verbindung zu testen
                if await self._test_connection(user_input):
                    return self.async_create_entry(
                        title=f"Controme {user_input[CONF_HAUS_ID]}", 
                        data=user_input
                    )
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_URL, description={"suggested_value": "http://"}): str,
                vol.Required(CONF_HAUS_ID): int,
                vol.Required(CONF_USER): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors
        )

    async def _test_connection(self, config: dict[str, Any]) -> bool:
        """Test the connection to the Controme API.
        
        Hier sollte ein echter Verbindungsversuch implementiert werden.
        Momentan wird standardmäßig True zurückgegeben.
        """
        # TODO: Implementieren Sie den Verbindungstest zur Controme API.
        return True 