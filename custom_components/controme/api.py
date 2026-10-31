"""Read and write access to the Controme API for single rooms."""
import logging
import re
from typing import Any, Dict, Optional
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

# Writes are only allowed for a single room: soll/ziel/rooms need a room ID in the URL.
# Without the room ID, rooms/ and temperaturszenen/ would change ALL rooms.
ROOM_WRITE_PATH = re.compile(r"^/set/json/v1/[0-9]+/(soll|ziel|rooms)/([0-9]+)/$")
SCENE_WRITE_PATH = re.compile(r"^/set/json/v1/[0-9]+/temperaturszenen/([0-9]+)/$")
ROOM_ID = re.compile(r"^[0-9]+$")


def room_write_url(base_url: str, house_id: Any, kind: str, room_id: Any) -> str:
    """Return the write URL of a room ("soll", "ziel" or "rooms")."""
    return f"{base_url.rstrip('/')}/set/json/v1/{house_id}/{kind}/{room_id}/"


def scene_write_url(base_url: str, house_id: Any, scene_id: Any) -> str:
    """Return the write URL of a scene, the room is sent as room_id in the body."""
    return f"{base_url.rstrip('/')}/set/json/v1/{house_id}/temperaturszenen/{scene_id}/"


def check_single_room_write(endpoint: str, data: Dict[str, Any]) -> None:
    """Raise ValueError unless the write targets exactly one room.

    POSTs to /rooms/ without a room ID or to /temperaturszenen/{id}/ without
    room_id would change all rooms, so they are never sent.
    """
    path = urlsplit(endpoint).path
    if ROOM_WRITE_PATH.match(path):
        return
    if SCENE_WRITE_PATH.match(path) and ROOM_ID.match(str(data.get("room_id", ""))):
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
    check_single_room_write(endpoint, data)
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


async def async_get_json(hass: HomeAssistant, endpoint: str) -> Optional[Any]:
    """GET JSON from the read API (no credentials), returning None on errors."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(endpoint, timeout=REQUEST_TIMEOUT) as response:
            if response.status != 200:
                _LOGGER.debug("Controme read failed: URL=%s, status=%s", endpoint, response.status)
                return None
            return await response.json(content_type=None)
    except (ClientError, TimeoutError, ValueError) as err:
        _LOGGER.debug("Controme read failed: URL=%s, Error=%s", endpoint, type(err).__name__)
        return None
