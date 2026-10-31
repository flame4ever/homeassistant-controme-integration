"""The Controme integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from .coordinator import ContromeConfigEntry, ContromeDataUpdateCoordinator
from .api import SHORT_REQUEST_TIMEOUT, async_get_json, info_read_url
from .const import DOMAIN, CONF_HAUS_ID, CONF_API_URL
from .helpers import hub_versions
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.CLIMATE, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Controme services (once, independent of config entries)."""
    async_setup_services(hass)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ContromeConfigEntry) -> bool:
    """Set up Controme from a config entry."""
    coordinator = ContromeDataUpdateCoordinator(
        hass,
        entry,
        entry.data[CONF_API_URL],
        entry.data[CONF_HAUS_ID],
    )
    
    await coordinator.async_config_entry_first_refresh()

    # Software and hardware version of the hub, only set if /info/ reports them
    versions = await async_get_hub_versions(hass, entry.data[CONF_API_URL], entry.data[CONF_HAUS_ID])

    # Register the main Controme hub device, room devices link to it via its ID
    device_registry = dr.async_get(hass)
    hub_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.data[CONF_HAUS_ID])},
        manufacturer="Controme",
        name=f"Controme Home {entry.data[CONF_HAUS_ID]}",
        model="Thermostat API",
        **versions,
    )
    coordinator.hub_device_id = hub_device.id

    entry.runtime_data = coordinator

    # Reload the entry when the options (stale sensor threshold) change
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_get_hub_versions(hass: HomeAssistant, base_url: str, house_id: str) -> dict[str, str]:
    """Read /info/ once (no credentials, 5 s timeout) and return sw_version/hw_version.

    Errors, timeouts, unreadable JSON and an empty answer ({}) only return {},
    so the setup never fails because of the info.
    """
    info = await async_get_json(hass, info_read_url(base_url, house_id), SHORT_REQUEST_TIMEOUT)
    versions = hub_versions(info)
    if not versions:
        _LOGGER.debug("Controme /info/ reports no software or hardware version")
    return versions

async def _async_update_listener(hass: HomeAssistant, entry: ContromeConfigEntry) -> None:
    """Reload the config entry after its options were changed."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ContromeConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)