"""Write access to the Controme API for single rooms."""
import logging
import re
from typing import Any, Dict
from urllib.parse import urlsplit

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = ClientTimeout(total=10)  # 10 Sekunden Timeout
# Responses are only logged shortened
MAX_LOGGED_RESPONSE = 200

# Writes are only allowed for a single room: soll/ziel with a numeric room ID in the URL.
# Endpoints without a room (e.g. temperaturszenen/ or rooms/) would change ALL rooms.
ROOM_WRITE_PATH = re.compile(r"^/set/json/v1/[0-9]+/(soll|ziel)/([0-9]+)/$")


def room_write_url(base_url: str, house_id: Any, kind: str, room_id: Any) -> str:
    """Return the write URL of a room ("soll" or "ziel")."""
    return f"{base_url.rstrip('/')}/set/json/v1/{house_id}/{kind}/{room_id}/"


def check_single_room_write(endpoint: str) -> None:
    """Raise ValueError unless the write targets exactly one room."""
    path = urlsplit(endpoint).path
    if ROOM_WRITE_PATH.match(path):
        return
    raise ValueError(f"Refusing Controme write without a single room: {path}")


def _safe_for_log(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the form data without credentials."""
    return {key: value for key, value in data.items() if key not in ("user", "password")}


async def async_post(
    hass: HomeAssistant, endpoint: str, data: Dict[str, Any], user: str, password: str
) -> str:
    """POST form data plus credentials to a single room endpoint and return the response text.

    Raises ValueError for writes that would affect more than one room and a
    translated HomeAssistantError (auth_failed or write_failed) on errors.
    """
    check_single_room_write(endpoint)
    session = async_get_clientsession(hass)
    _LOGGER.debug("Controme write: URL=%s, Data=%s", endpoint, _safe_for_log(data))
    try:
        async with session.post(
            endpoint,
            data={**data, "user": user, "password": password},
            headers={
                'Content-Type': 'application/x-www-form-urlencoded',
                'Accept': 'application/json'
            },
            timeout=REQUEST_TIMEOUT,
        ) as response:
            status = response.status
            response_text = await response.text()
    except (ClientError, TimeoutError) as err:
        # Only the error type is passed on, the request data holds the credentials
        _LOGGER.debug("Controme write failed: URL=%s, Error=%s", endpoint, type(err).__name__)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="write_failed",
            translation_placeholders={"error": type(err).__name__},
        ) from err

    _LOGGER.debug("Controme write response: status=%s, Response=%s",
                  status, response_text[:MAX_LOGGED_RESPONSE])
    if status in (401, 403):
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="auth_failed")
    if status != 200:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="write_failed",
            translation_placeholders={"error": f"HTTP {status}"},
        )
    return response_text
