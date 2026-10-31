"""Offline tests for the Controme write actions (no Home Assistant, no network).

Run with: python tests/test_write_actions.py
"""
import asyncio
import json
import logging
from datetime import timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ha_stubs  # noqa: E402

ha_stubs.install(timezone(timedelta(hours=1)))

import custom_components.controme as integration  # noqa: E402
from custom_components.controme import api, climate, helpers, services  # noqa: E402

SESSION = ha_stubs.SESSION
HVACMode = ha_stubs.HVACMode
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
                                        "password": PASSWORD}, "options": {},
                               "entry_id": "entry1"})()
    coordinator = FakeCoordinator([floor])
    return climate.ContromeClimate(coordinator, entry, room, {}), coordinator


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
        (f"{BASE}/set/json/v1/1/rooms/13/", {"action": "betriebsart", "value": "off"}),
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


# R8-01: hvac mode is read only again (same as 2.1.0)
def test_hvac_modes_only_reported_mode():
    entity, _ = make_climate()
    assert entity._attr_hvac_modes == [HVACMode.HEAT]
    assert entity._attr_hvac_mode == HVACMode.HEAT
    assert entity._attr_supported_features == ha_stubs.ClimateEntityFeature.TARGET_TEMPERATURE
    for betriebsart, mode in (("off", HVACMode.OFF), ("cooling", HVACMode.COOL), (1, HVACMode.COOL)):
        entity, _ = make_climate({"id": 13, "name": "R", "betriebsart": betriebsart})
        assert entity._attr_hvac_modes == [mode]
        assert entity._attr_hvac_mode == mode
    assert "async_turn_on" not in vars(climate.ContromeClimate)
    assert "async_turn_off" not in vars(climate.ContromeClimate)


def test_set_hvac_mode_never_writes():
    for mode in (HVACMode.OFF, HVACMode.COOL):
        reset()
        entity, coordinator = make_climate()
        err = raises(ha_stubs.ServiceValidationError, asyncio.run, entity.async_set_hvac_mode(mode))
        assert (err.translation_domain, err.translation_key) == ("controme", "hvac_mode_not_supported")
        assert err.translation_placeholders == {"mode": str(mode)}
        assert SESSION.posts == [] and SESSION.gets == []
        assert coordinator.refreshes == 0
    # The current mode is a no-op
    reset()
    entity, _ = make_climate()
    asyncio.run(entity.async_set_hvac_mode(HVACMode.HEAT))
    assert SESSION.posts == []


def test_synthetic_room_error_translated():
    reset()
    entity, _ = make_climate({"name": "Floor", "temperatur": 20.0, "betriebsart": "Heating"})
    err = raises(ha_stubs.ServiceValidationError, asyncio.run, entity.async_set_temperature(temperature=21.0))
    assert (err.translation_domain, err.translation_key) == ("controme", "not_a_room")
    assert err.translation_placeholders == {"room_id": "5_0"}
    assert SESSION.posts == []


def test_services_need_loaded_entry():
    ha_stubs.UNLOADED_ENTRIES.add("entry1")
    try:
        for call in ({"temperature": 21.0}, {"scene_id": 1}):
            reset()
            entity, _ = make_climate()
            method = (entity.async_set_temporary_temperature if "temperature" in call
                      else entity.async_activate_scene)
            err = raises(ha_stubs.ServiceValidationError, asyncio.run, method(**call))
            assert err.translation_key == "service_config_entry_not_loaded"
            assert SESSION.posts == [] and SESSION.gets == []
    finally:
        ha_stubs.UNLOADED_ENTRIES.clear()


def test_all_raised_errors_are_translated():
    # Every HomeAssistantError/ServiceValidationError raised in the integration
    # uses translation_domain/translation_key and no plain text message
    import re
    package = ha_stubs.ROOT / "custom_components" / "controme"
    translations = json.loads((package / "translations" / "en.json").read_text(encoding="utf-8"))
    used = set()
    for path in package.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"raise (HomeAssistantError|ServiceValidationError)\(([^)]*)", source):
            assert "translation_key=" in match.group(2), f"{path.name}: {match.group(0)}"
            assert "translation_domain=DOMAIN" in match.group(2), f"{path.name}: {match.group(0)}"
            used.update(re.findall(r'translation_key="([a-z_]+)"', match.group(2)))
    assert used, "no translated errors found"
    assert used <= set(translations["exceptions"]), used - set(translations["exceptions"])


# S4-03: temporary temperature
def test_ziel_with_and_without_duration():
    for duration, expected in ((None, "default"), (2, "2"), (1440, "1440")):
        reset()
        entity, coordinator = make_climate()
        if duration is None:
            asyncio.run(entity.async_set_temporary_temperature(temperature=21.5))
        else:
            asyncio.run(entity.async_set_temporary_temperature(temperature=21.5, duration=duration))
        assert SESSION.posts[0]["url"] == "http://controme.local/set/json/v1/1/ziel/13/"
        assert SESSION.posts[0]["data"] == {"ziel": "21.5", "duration": expected,
                                            "user": USER, "password": PASSWORD}
        assert coordinator.refreshes == 1
        assert entity._attr_target_temperature == 21.5


def test_ziel_synthetic_room():
    reset()
    entity, _ = make_climate({"name": "Floor", "temperatur": 20.0})
    raises(ha_stubs.ServiceValidationError, asyncio.run, entity.async_set_temporary_temperature(temperature=21.0))
    assert SESSION.posts == []


def test_service_temperature_limits():
    for value, expected in ((5, 5.0), ("21.5", 21.5), (30, 30.0), (22.0, 22.0)):
        assert services.validate_temperature(value) == expected
    for value in (4.5, 30.5, 35, 21.3, "abc", None, True):
        raises(ha_stubs.Invalid, services.validate_temperature, value)


def test_service_duration_limits():
    for value, expected in ((1, 1), ("2", 2), (1440, 1440), (60.0, 60)):
        assert services.validate_duration(value) == expected
    for value in (0, -1, 1441, 1.5, "abc", None, True):
        raises(ha_stubs.Invalid, services.validate_duration, value)


def test_services_registered_in_async_setup():
    registry = sys.modules["homeassistant.helpers.service"].registered
    registry.clear()
    assert asyncio.run(integration.async_setup(None, {})) is True
    registered = {name: kwargs for _domain, name, kwargs in registry}
    assert all(domain == "controme" for domain, _name, _kwargs in registry)
    assert registered["set_temporary_temperature"]["entity_domain"] == "climate"
    assert registered["set_temporary_temperature"]["func"] == "async_set_temporary_temperature"


def test_services_yaml_matches_schema():
    try:
        import yaml
    except ImportError as err:
        raise unittest.SkipTest("PyYAML not installed") from err
    path = ha_stubs.ROOT / "custom_components" / "controme" / "services.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    fields = data["set_temporary_temperature"]["fields"]
    assert fields["temperature"]["selector"]["number"] == {
        "min": 5, "max": 30, "step": 0.5, "unit_of_measurement": "°C", "mode": "box"}
    assert fields["duration"]["selector"]["number"]["min"] == 1
    assert fields["duration"]["selector"]["number"]["max"] == 1440
    assert data["set_temporary_temperature"]["target"]["entity"] == {
        "integration": "controme", "domain": "climate"}
    assert set(data) == {"set_temporary_temperature", "activate_scene"}
    assert data["activate_scene"]["target"]["entity"] == {"integration": "controme", "domain": "climate"}
    assert set(data["activate_scene"]["fields"]) == {"scene_id", "duration"}
    assert data["activate_scene"]["fields"]["scene_id"]["required"] is True


def test_temporary_attributes_only_when_reported():
    entity, _ = make_climate()
    assert entity.extra_state_attributes == {}
    room = {"id": 13, "name": "R", "solltemperatur": 21.5, "is_temporary_mode": True,
            "mode_end_datetime": "2026-10-31 14:30:00", "perm_solltemperatur": "21.0"}
    entity, _ = make_climate(room)
    attributes = entity.extra_state_attributes
    assert attributes["temporary_mode"] is True
    assert attributes["temporary_until"].isoformat() == "2026-10-31T14:30:00+01:00"
    assert attributes["permanent_target_temperature"] == 21.0
    entity, _ = make_climate({"id": 13, "name": "R", "is_temporary_mode": "false",
                              "mode_end_datetime": ""})
    assert entity.extra_state_attributes == {"temporary_mode": False, "temporary_until": None}


# S4-04: scenes
LIVE_SCENES = [{"id": 1, "Name": "*", "raeume": [
    {"active": True, "temperatur": 22.0, "name": "Keller / Sportzimmer"}]}]


def test_parse_scenes():
    assert helpers.parse_scenes(LIVE_SCENES) == {1: "*"}
    messy = [{"id": "2", "name": "Lower"}, {"id": 3}, {"Name": "no id"}, {"id": True, "Name": "bool"},
             {"id": "x", "Name": "bad"}, None, "text", {"id": 4, "Name": ""}]
    assert helpers.parse_scenes(messy) == {2: "Lower", 3: "3", 4: "4"}
    for data in (None, {}, "x", 1):
        assert helpers.parse_scenes(data) == {}


def test_activate_scene_with_room_id():
    for duration, expected in ((None, {"room_id": "13"}), (2, {"room_id": "13", "duration": "2"})):
        reset()
        entity, coordinator = make_climate()
        SESSION.get_responses.append(FakeResponse(payload=LIVE_SCENES))
        if duration is None:
            asyncio.run(entity.async_activate_scene(scene_id=1))
        else:
            asyncio.run(entity.async_activate_scene(scene_id=1, duration=duration))
        assert SESSION.gets == ["http://controme.local/get/json/v1/1/temperaturszenen/"]
        assert SESSION.posts[0]["url"] == "http://controme.local/set/json/v1/1/temperaturszenen/1/"
        assert SESSION.posts[0]["data"] == {**expected, "user": USER, "password": PASSWORD}
        assert coordinator.refreshes == 1


def test_activate_unknown_scene():
    reset()
    entity, _ = make_climate()
    SESSION.get_responses.append(FakeResponse(payload=LIVE_SCENES))
    err = raises(ha_stubs.ServiceValidationError, asyncio.run, entity.async_activate_scene(scene_id=99))
    assert err.translation_key == "unknown_scene"
    assert err.translation_placeholders == {"scene_id": "99", "scenes": "1 (*)"}
    assert SESSION.posts == []


def test_activate_scene_list_unavailable():
    reset()
    entity, _ = make_climate()
    SESSION.get_responses.append(FakeResponse(500))
    err = raises(ha_stubs.HomeAssistantError, asyncio.run, entity.async_activate_scene(scene_id=1))
    assert err.translation_key == "write_failed"
    assert SESSION.posts == []


def test_activate_scene_synthetic_room():
    reset()
    entity, _ = make_climate({"name": "Floor", "temperatur": 20.0})
    raises(ha_stubs.ServiceValidationError, asyncio.run, entity.async_activate_scene(scene_id=1))
    assert SESSION.posts == [] and SESSION.gets == []


def test_service_scene_id_limits():
    for value, expected in ((1, 1), ("2", 2), (99.0, 99)):
        assert services.validate_scene_id(value) == expected
    for value in (0, -1, 1.5, "abc", None, True):
        raises(ha_stubs.Invalid, services.validate_scene_id, value)


def test_activate_scene_registered():
    registry = sys.modules["homeassistant.helpers.service"].registered
    registry.clear()
    asyncio.run(integration.async_setup(None, {}))
    registered = {name: kwargs for _domain, name, kwargs in registry}
    assert registered["activate_scene"]["entity_domain"] == "climate"
    assert registered["activate_scene"]["func"] == "async_activate_scene"
    # No scene platform and no service without a climate target
    assert set(registered) == {"set_temporary_temperature", "activate_scene"}
    assert "scene" not in [str(platform).lower() for platform in integration.PLATFORMS]


def run(namespace):
    failures = 0
    skipped = 0
    tests = [(name, func) for name, func in sorted(namespace.items()) if name.startswith("test_")]
    for name, func in tests:
        try:
            func()
            print(f"OK   {name}")
        except unittest.SkipTest as err:
            skipped += 1
            print(f"SKIP {name}: {err}")
        except Exception as err:  # noqa: BLE001
            failures += 1
            print(f"FAIL {name}: {type(err).__name__}: {err}")
    # No credentials in any log line of the whole run
    leaked = [message for message in LOGS.messages if PASSWORD in message or USER in message]
    if leaked:
        failures += 1
        print(f"FAIL credentials in logs: {leaked}")
    print(f"{len(tests) - failures - skipped}/{len(tests)} tests passed, {skipped} skipped")
    return failures


if __name__ == "__main__":
    sys.exit(1 if run(dict(globals())) else 0)
