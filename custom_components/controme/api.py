"""Write access to the Controme API for single rooms (and the reads it needs)."""
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
# Optional reads (system info, scene list) must not delay setup or updates for long
SHORT_REQUEST_TIMEOUT = ClientTimeout(total=5)
# Responses are only logged shortened
MAX_LOGGED_RESPONSE = 200

# Writes are only allowed for a single room: soll/ziel with a numeric room ID in the URL,
# scenes with a numeric scene ID in the URL and a numeric room_id in the body.
# Endpoints without a room (rooms/ or a scene without room_id) would change ALL rooms.
ROOM_WRITE_PATH = re.compile(r"^/set/json/v1/[0-9]+/(soll|ziel)/([0-9]+)/$")
SCENE_WRITE_PATH = re.compile(r"^/set/json/v1/[0-9]+/temperaturszenen/([0-9]+)/$")
NUMERIC_ID = re.compile(r"^[0-9]+$")


def room_write_url(base_url: str, house_id: Any, kind: str, room_id: Any) -> str:
    """Return the write URL of a room ("soll" or "ziel")."""
    return f"{base_url.rstrip('/')}/set/json/v1/{house_id}/{kind}/{room_id}/"


def scene_write_url(base_url: str, house_id: Any, scene_id: Any) -> str:
    """Return the write URL of a scene, the room is sent as room_id in the body."""
    return f"{base_url.rstrip('/')}/set/json/v1/{house_id}/temperaturszenen/{scene_id}/"


def scenes_read_url(base_url: str, house_id: Any) -> str:
    """Return the read URL of the scene list."""
    return f"{base_url.rstrip('/')}/get/json/v1/{house_id}/temperaturszenen/"


def info_read_url(base_url: str, house_id: Any) -> str:
    """Return the read URL of the system info (hw, sw-date, branch; empty on some firmwares)."""
    return f"{base_url.rstrip('/')}/get/json/v1/{house_id}/info/"


async def async_get_json(
    hass: HomeAssistant, endpoint: str, timeout: ClientTimeout = REQUEST_TIMEOUT
) -> Optional[Any]:
    """GET JSON from the read API (no credentials), returning None on errors."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(endpoint, timeout=timeout) as response:
            if response.status != 200:
                _LOGGER.debug("Controme read failed: URL=%s, status=%s", endpoint, response.status)
                return None
            return await response.json(content_type=None)
    except (ClientError, TimeoutError, ValueError) as err:
        _LOGGER.debug("Controme read failed: URL=%s, Error=%s", endpoint, type(err).__name__)
        return None


def check_single_room_write(base_url: str, endpoint: str, data: Dict[str, Any]) -> None:
    """Raise a translated HomeAssistantError unless the write targets exactly one room.

    The path is checked relative to the configured base URL, so base URLs with
    a path prefix (e.g. http://host/controme) work.
    """
    base = base_url.rstrip('/')
    relative = endpoint[len(base):] if endpoint.startswith(base + "/") else ""
    room_id = data.get("room_id")
    # fullmatch, because "$" would also accept a trailing newline
    allowed = bool(ROOM_WRITE_PATH.fullmatch(relative)) or (
        bool(SCENE_WRITE_PATH.fullmatch(relative))
        and isinstance(room_id, (str, int))
        and not isinstance(room_id, bool)
        and bool(NUMERIC_ID.fullmatch(str(room_id)))
    )
    # Query strings or fragments are never part of a room write
    if not allowed or urlsplit(endpoint).query or "#" in endpoint:
        _LOGGER.debug("Refusing Controme write without a single room: %s", endpoint)
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="invalid_write_target")


def _safe_for_log(data: Dict[str, Any]) -> Dict[str, Any]:
    """Return the form data without credentials."""
    return {key: value for key, value in data.items() if key not in ("user", "password")}


async def async_post(
    hass: HomeAssistant,
    base_url: str,
    endpoint: str,
    data: Dict[str, Any],
    user: str,
    password: str,
) -> str:
    """POST form data plus credentials to a single room endpoint and return the response text.

    Raises a translated HomeAssistantError: invalid_write_target for writes that
    do not target exactly one room (nothing is sent), auth_failed or write_failed.
    """
    check_single_room_write(base_url, endpoint, data)
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
