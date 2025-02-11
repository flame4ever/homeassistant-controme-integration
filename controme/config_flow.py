import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN

@callback
def configured_instances(hass):
    return [entry.data.get("api_url") for entry in hass.config_entries.async_entries(DOMAIN)]

class ContromeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            if user_input["api_url"] in configured_instances(self.hass):
                errors["base"] = "already_configured"
            else:
                return self.async_create_entry(title="Controme", data=user_input)

        data_schema = vol.Schema({
            vol.Required("api_url"): str,
            vol.Required("haus_id"): int,
            vol.Required("user"): str,
            vol.Required("password"): str,
        })

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )
    