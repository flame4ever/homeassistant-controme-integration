"""Offline tests for the Controme write actions (no Home Assistant, no network).

Run with: python tests/test_write_actions.py
"""
import asyncio
import logging
from datetime import timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ha_stubs  # noqa: E402

ha_stubs.install(timezone(timedelta(hours=1)))

from custom_components.controme import api, climate  # noqa: E402

SESSION = ha_stubs.SESSION
HVACMode = ha_stubs.HVACMode
SLEEPS = []


async def _fake_sleep(seconds):
    SLEEPS.append(seconds)


climate.asyncio.sleep = _fake_sleep


class FakeCoordinator:
    def __init__(self, data):
        self.data = data
        self.hass = object()
        self.last_update_success = True
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1


def make_climate(room=None):
    """Return a climate entity for room 13 (or the given room dict) on floor 5."""
    room = room or {"id": 13, "name": "Testraum", "temperatur": 21.7, "solltemperatur": 21.0,
                    "betriebsart": "Heating"}
    floor = {"id": 5, "raeume": [room]}
    room["floor_id"], room["room_id"] = 5, room.get("id", "5_0")
    entry = type("Entry", (), {"data": {"api_url": BASE, "haus_id": "1", "user": USER,
                                        "password": PASSWORD}, "options": {}})()
    coordinator = FakeCoordinator([floor])
    return climate.ContromeClimate(coordinator, entry, room, {}), coordinator


def temps_room(betriebsart):
    """A /temps/13/ response (list of floors) reporting the given betriebsart."""
    return FakeResponse(payload=[{"id": 5, "raeume": [{"id": 13, "betriebsart": betriebsart}]}])
FakeResponse = ha_stubs.FakeResponse
BASE = "http://controme.local"
USER, PASSWORD = "ha-user", "s3cret-pw"


class LogCapture(logging.Handler):
    """Collect all log output of the integration."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


LOGS = LogCapture()
logging.getLogger("custom_components.controme").addHandler(LOGS)
logging.getLogger("custom_components.controme").setLevel(logging.DEBUG)


def reset():
    SESSION.posts.clear()
    SESSION.gets.clear()
    SESSION.post_responses.clear()
    SESSION.get_responses.clear()


def post(endpoint, data):
    return asyncio.run(api.async_post(None, endpoint, data, USER, PASSWORD))


def raises(exc_type, func, *args):
    try:
        func(*args)
    except exc_type as err:
        return err
    raise AssertionError(f"{exc_type.__name__} not raised")


def assert_no_credentials(*texts):
    for text in texts:
        assert PASSWORD not in str(text), f"password leaked: {text}"
        assert USER not in str(text), f"user leaked: {text}"


# S4-01: URLs and bodies
def test_soll_url_and_body():
    reset()
    assert post(api.room_write_url(BASE, "1", "soll", 13), {"soll": "21.0"}) == ""
    assert SESSION.posts == [{
        "url": "http://controme.local/set/json/v1/1/soll/13/",
        "data": {"soll": "21.0", "user": USER, "password": PASSWORD},
        "timeout": api.REQUEST_TIMEOUT,
    }]


def test_credentials_cannot_be_overridden_by_data():
    reset()
    post(api.room_write_url(BASE, "1", "soll", 13), {"soll": "21.0", "user": "x", "password": "y"})
    assert SESSION.posts[0]["data"]["user"] == USER
    assert SESSION.posts[0]["data"]["password"] == PASSWORD


def test_scene_url_with_room_id():
    reset()
    post(api.scene_write_url(BASE, "1", 1), {"room_id": "13", "duration": "2"})
    assert SESSION.posts[0]["url"] == "http://controme.local/set/json/v1/1/temperaturszenen/1/"
    assert SESSION.posts[0]["data"] == {"room_id": "13", "duration": "2", "user": USER, "password": PASSWORD}


# S4-01: guard against writes for all rooms
def test_guard_blocks_writes_without_room():
    reset()
    blocked = [
        (f"{BASE}/set/json/v1/1/rooms/", {"action": "betriebsart", "value": "off"}),
        (f"{BASE}/set/json/v1/1/rooms", {"action": "betriebsart", "value": "off"}),
        (f"{BASE}/set/json/v1/1/soll/", {"soll": "21.0"}),
        (f"{BASE}/set/json/v1/1/ziel/", {"ziel": "21.0", "duration": "default"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"duration": "2"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": ""}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": None}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": "1,2"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/", {"room_id": "13"}),
        (f"{BASE}/set/json/v1/1/rooms/1_0/", {"action": "betriebsart", "value": "off"}),
        (f"{BASE}/set/json/v1/1/rooms/13/extra/", {"action": "betriebsart", "value": "off"}),
        (f"{BASE}/set/json/v1/1/quickui/", {"duration": "60"}),
        (f"{BASE}/set/json/v1/1/rooms/?id=13", {"action": "betriebsart", "value": "off"}),
    ]
    for endpoint, data in blocked:
        raises(ValueError, post, endpoint, data)
    assert SESSION.posts == [], SESSION.posts


# S4-01: error mapping
def test_403_auth_failed():
    reset()
    SESSION.post_responses.append(FakeResponse(403, "Forbidden"))
    err = raises(ha_stubs.HomeAssistantError, post, api.room_write_url(BASE, 1, "soll", 13), {"soll": "21.0"})
    assert (err.translation_domain, err.translation_key) == ("controme", "auth_failed")


def test_500_and_timeout_write_failed():
    for response, detail in ((FakeResponse(500, "boom"), "HTTP 500"),
                             (TimeoutError(), "TimeoutError"),
                             (ha_stubs.ClientError(f"POST failed user={USER} password={PASSWORD}"), "ClientError")):
        reset()
        SESSION.post_responses.append(response)
        err = raises(ha_stubs.HomeAssistantError, post, api.room_write_url(BASE, 1, "soll", 13), {"soll": "21.0"})
        assert err.translation_key == "write_failed"
        assert err.translation_placeholders == {"error": detail}
        assert_no_credentials(err, err.translation_placeholders)


def test_response_logged_shortened_without_credentials():
    reset()
    LOGS.messages.clear()
    SESSION.post_responses.append(FakeResponse(200, "x" * 1000))
    post(api.room_write_url(BASE, 1, "soll", 13), {"soll": "21.0"})
    assert any("x" * api.MAX_LOGGED_RESPONSE in message for message in LOGS.messages)
    assert not any("x" * (api.MAX_LOGGED_RESPONSE + 1) in message for message in LOGS.messages)
    assert_no_credentials(*LOGS.messages)


# S4-01: set_temperature (soll) through the climate entity
def test_climate_set_temperature_soll():
    reset()
    entity, coordinator = make_climate()
    asyncio.run(entity.async_set_temperature(temperature=21.5))
    assert [p["url"] for p in SESSION.posts] == ["http://controme.local/set/json/v1/1/soll/13/"]
    assert SESSION.posts[0]["data"] == {"soll": "21.5", "user": USER, "password": PASSWORD}
    assert coordinator.refreshes == 1


# S4-02: hvac mode
def test_hvac_modes():
    entity, _ = make_climate()
    assert entity._attr_hvac_modes == [HVACMode.HEAT, HVACMode.OFF]
    assert entity._attr_hvac_mode == HVACMode.HEAT
    cooling, _ = make_climate({"id": 13, "name": "R", "betriebsart": "cooling"})
    assert cooling._attr_hvac_modes == [HVACMode.HEAT, HVACMode.OFF, HVACMode.COOL]
    assert cooling._attr_hvac_mode == HVACMode.COOL


def test_set_hvac_mode_off_and_heat_confirmed():
    for mode, value, reported in ((HVACMode.OFF, "off", "off"), (HVACMode.HEAT, "heating", "Heating")):
        reset()
        SLEEPS.clear()
        entity, coordinator = make_climate()
        SESSION.get_responses.extend([temps_room("Heating" if mode == HVACMode.OFF else "off"),
                                      temps_room(reported)])
        asyncio.run(entity.async_set_hvac_mode(mode))
        assert SESSION.posts == [{
            "url": "http://controme.local/set/json/v1/1/rooms/13/",
            "data": {"action": "betriebsart", "value": value, "user": USER, "password": PASSWORD},
            "timeout": api.REQUEST_TIMEOUT,
        }]
        assert SESSION.gets == ["http://controme.local/get/json/v1/1/temps/13/"] * 2
        assert SLEEPS == [2, 3], SLEEPS
        assert entity._attr_hvac_mode == mode
        assert coordinator.refreshes == 1


def test_set_hvac_mode_not_applied():
    reset()
    SLEEPS.clear()
    entity, coordinator = make_climate()
    SESSION.get_responses.extend([temps_room("Heating")] * 3)
    err = raises(ha_stubs.HomeAssistantError, asyncio.run, entity.async_set_hvac_mode(HVACMode.OFF))
    assert err.translation_key == "mode_not_applied"
    assert err.translation_placeholders == {"mode": "off", "value": "Heating"}
    assert SLEEPS == [2, 3, 5]
    assert coordinator.refreshes == 1


def test_set_hvac_mode_unreadable_counts_as_applied():
    reset()
    SLEEPS.clear()
    entity, coordinator = make_climate()
    SESSION.get_responses.extend([TimeoutError(), FakeResponse(500), FakeResponse(payload=[])])
    asyncio.run(entity.async_set_hvac_mode(HVACMode.OFF))
    assert len(SESSION.posts) == 1 and coordinator.refreshes == 1


def test_set_hvac_mode_cool_never_sent():
    reset()
    entity, _ = make_climate({"id": 13, "name": "R", "betriebsart": "cooling"})
    err = raises(ha_stubs.ServiceValidationError, asyncio.run, entity.async_set_hvac_mode(HVACMode.COOL))
    assert err.translation_key == "unsupported_hvac_mode"
    assert SESSION.posts == []
    assert set(climate.HVAC_MODE_TO_BETRIEBSART.values()) == {"heating", "off"}


def test_set_hvac_mode_synthetic_room():
    reset()
    entity, _ = make_climate({"name": "Floor", "temperatur": 20.0, "betriebsart": "Heating"})
    raises(ha_stubs.ServiceValidationError, asyncio.run, entity.async_set_hvac_mode(HVACMode.OFF))
    assert SESSION.posts == []


def run(namespace):
    failures = 0
    tests = [(name, func) for name, func in sorted(namespace.items()) if name.startswith("test_")]
    for name, func in tests:
        try:
            func()
            print(f"OK   {name}")
        except unittest.SkipTest as err:
            print(f"SKIP {name}: {err}")
        except Exception as err:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {type(err).__name__}: {err}")
    # No credentials in any log line of the whole run
    leaked = [message for message in LOGS.messages if PASSWORD in message or USER in message]
    if leaked:
        failures += 1
        print(f"FAIL credentials in logs: {leaked}")
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if run(dict(globals())) else 0)
