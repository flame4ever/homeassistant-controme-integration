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


def post(endpoint, data, base_url=None):
    return asyncio.run(api.async_post(None, base_url or BASE, endpoint, data, USER, PASSWORD))


def raises(exc_type, func, *args, **kwargs):
    try:
        func(*args, **kwargs)
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
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": "abc"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": "-13"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": "13\n"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": " 13"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": "5_0"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": True}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/1/", {"room_id": ["13"]}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/x/", {"room_id": "13"}),
        (f"{BASE}/set/json/v1/1/temperaturszenen/", {"room_id": "13"}),
        (f"{BASE}/set/json/v1/1/soll/13/\n", {"soll": "21.0"}),
        (f"{BASE}/set/json/v1/1/rooms/1_0/", {"action": "betriebsart", "value": "off"}),
        (f"{BASE}/set/json/v1/1/rooms/13/", {"action": "betriebsart", "value": "off"}),
        (f"{BASE}/set/json/v1/1/rooms/13/extra/", {"action": "betriebsart", "value": "off"}),
        (f"{BASE}/set/json/v1/1/quickui/", {"duration": "60"}),
        (f"{BASE}/set/json/v1/1/rooms/?id=13", {"action": "betriebsart", "value": "off"}),
    ]
    for endpoint, data in blocked:
        err = raises(ha_stubs.HomeAssistantError, post, endpoint, data)
        assert (err.translation_domain, err.translation_key) == ("controme", "invalid_write_target")
    assert SESSION.posts == [], SESSION.posts


# S4b-01: scene writes with a numeric room_id pass the guard, also with a path prefix
def test_guard_allows_scene_with_room_id():
    for base, room_id in ((BASE, "13"), (BASE, 13), ("http://host/controme", "13")):
        reset()
        url = api.scene_write_url(base, "1", 2)
        post(url, {"room_id": room_id, "duration": "2"}, base_url=base)
        assert SESSION.posts[0]["url"] == f"{base}/set/json/v1/1/temperaturszenen/2/"
        assert SESSION.posts[0]["data"]["room_id"] == room_id
    reset()
    for base, endpoint, data in (
        ("http://host/controme", "http://host/controme/set/json/v1/1/temperaturszenen/2/", {}),
        ("http://host/controme", "http://host/controme/set/json/v1/1/temperaturszenen/2/", {"room_id": ""}),
        ("http://host", "http://host/controme/set/json/v1/1/temperaturszenen/2/", {"room_id": "13"}),
    ):
        err = raises(ha_stubs.HomeAssistantError, post, endpoint, data, base)
        assert err.translation_key == "invalid_write_target"
    assert SESSION.posts == []


# R8-04: guard relative to the base URL (path prefix)
def test_guard_with_path_prefix():
    for base in ("http://host/controme", "http://host/controme/", "https://host:8443/a/b"):
        reset()
        url = api.room_write_url(base, "1", "ziel", 13)
        assert url == f"{base.rstrip('/')}/set/json/v1/1/ziel/13/"
        post(url, {"ziel": "21.5", "duration": "default"}, base_url=base)
        assert [p["url"] for p in SESSION.posts] == [url]
    blocked = [
        # Prefixed endpoint but base URL without the prefix (and vice versa)
        ("http://host", "http://host/controme/set/json/v1/1/soll/13/"),
        ("http://host/controme", "http://host/set/json/v1/1/soll/13/"),
        # Other host or a base URL that is only a string prefix
        ("http://host", "http://other/set/json/v1/1/soll/13/"),
        ("http://host/con", "http://host/controme/set/json/v1/1/soll/13/"),
        # Prefix, but no room
        ("http://host/controme", "http://host/controme/set/json/v1/1/rooms/"),
        ("http://host/controme", "http://host/controme/set/json/v1/1/temperaturszenen/1/"),
        ("http://host/controme", "http://host/controme/set/json/v1/1/soll/13/?x=1"),
        ("http://host/controme", "http://host/controme/set/json/v1/1/soll/13/#x"),
    ]
    reset()
    for base, endpoint in blocked:
        err = raises(ha_stubs.HomeAssistantError, post, endpoint, {"soll": "21.0"}, base)
        assert err.translation_key == "invalid_write_target", endpoint
    assert SESSION.posts == []


def test_climate_with_path_prefix():
    reset()
    entity, _ = make_climate()
    entity._base_url = "http://host/controme"
    asyncio.run(entity.async_set_temperature(temperature=21.0))
    assert SESSION.posts[0]["url"] == "http://host/controme/set/json/v1/1/soll/13/"


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
        reset()
        entity, _ = make_climate()
        err = raises(ha_stubs.ServiceValidationError, asyncio.run,
                     entity.async_set_temporary_temperature(temperature=21.0))
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
        assert entity._attr_target_temperature == 21.5


# R8-03: optimistic value, refresh delayed by async_call_later, cancelled on removal
def test_ziel_delayed_refresh():
    reset()
    ha_stubs.CALL_LATER.clear()
    entity, coordinator = make_climate()
    asyncio.run(entity.async_set_temporary_temperature(temperature=21.5, duration=5))
    # Optimistic value written at once, no immediate refresh
    assert entity._attr_target_temperature == 21.5 and entity.writes == 1
    assert coordinator.refreshes == 0
    assert [call["delay"] for call in ha_stubs.CALL_LATER] == [climate.DELAYED_REFRESH_SECONDS]
    assert climate.DELAYED_REFRESH_SECONDS == 10
    # A second call replaces the pending refresh
    asyncio.run(entity.async_set_temporary_temperature(temperature=22.0))
    assert ha_stubs.CALL_LATER[0]["cancelled"] is True
    assert ha_stubs.CALL_LATER[1]["cancelled"] is False
    # When the timer fires, the coordinator is refreshed
    asyncio.run(ha_stubs.CALL_LATER[1]["action"](None))
    assert coordinator.refreshes == 1
    assert entity._unsub_delayed_refresh is None


def test_ziel_delayed_refresh_cancelled_on_remove():
    reset()
    ha_stubs.CALL_LATER.clear()
    entity, coordinator = make_climate()
    asyncio.run(entity.async_added_to_hass())
    asyncio.run(entity.async_set_temporary_temperature(temperature=21.5))
    # Cancelled via async_on_remove, without overriding async_will_remove_from_hass
    assert "async_will_remove_from_hass" not in vars(climate.ContromeClimate)
    entity.simulate_remove()
    assert ha_stubs.CALL_LATER[0]["cancelled"] is True
    assert entity._unsub_delayed_refresh is None
    assert coordinator.refreshes == 0
    # Removal without a pending refresh is fine as well
    entity, _ = make_climate()
    asyncio.run(entity.async_added_to_hass())
    entity.simulate_remove()


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
    scene = data["activate_scene"]
    assert scene["target"]["entity"] == {"integration": "controme", "domain": "climate"}
    assert set(scene["fields"]) == {"scene_id", "duration"}
    assert scene["fields"]["scene_id"]["required"] is True
    assert scene["fields"]["scene_id"]["selector"]["number"]["min"] == 1
    assert scene["fields"]["duration"]["selector"]["number"]["max"] == 1440
    # Every service and field has a translation
    translations = json.loads((path.parent / "translations" / "en.json").read_text(encoding="utf-8"))
    for name, service_data in data.items():
        assert set(service_data["fields"]) == set(translations["services"][name]["fields"]), name


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


# S4b-03: activate_scene service
def make_scene_climate(room_id=13):
    """Climate entity in a house with the 11 rooms of ALL_LABELS (room 13 = TEST_LABEL)."""
    floors = [{"id": n, "etagenname": f"Etage {n}", "raeume": [{"id": n, "name": f"Raum {n}"}]}
              for n in range(1, 11)]
    floors.append({"id": 50, "etagenname": "Test (ßÜÖÄüöä)",
                   "raeume": [{"id": 13, "name": "Testraum (ßÜÖÄüöä)", "solltemperatur": 21.0}]})
    floor = next(f for f in floors if f["raeume"][0]["id"] == room_id)
    room = floor["raeume"][0]
    room["floor_id"], room["room_id"] = floor["id"], room_id
    entry = type("Entry", (), {"data": {"api_url": BASE, "haus_id": "1", "user": USER,
                                        "password": PASSWORD}, "options": {},
                               "entry_id": "entry1"})()
    coordinator = FakeCoordinator(floors)
    return climate.ContromeClimate(coordinator, entry, room, {}), coordinator


def scene_call(entity, **kwargs):
    return asyncio.run(entity.async_activate_scene(**kwargs))


def test_activate_scene_single_room():
    for duration, expected in ((None, {"room_id": "13"}), (2, {"room_id": "13", "duration": "2"})):
        reset()
        ha_stubs.CALL_LATER.clear()
        entity, coordinator = make_scene_climate()
        SESSION.get_responses.append(FakeResponse(payload=LIVE_SCENES))
        SESSION.post_responses.append(FakeResponse(200, '{"roomlist": {"13": 21.5}, "time": "17:01"}'))
        if duration is None:
            scene_call(entity, scene_id=2)
        else:
            scene_call(entity, scene_id=2, duration=duration)
        assert SESSION.gets == ["http://controme.local/get/json/v1/1/temperaturszenen/"]
        assert len(SESSION.posts) == 1
        assert SESSION.posts[0]["url"] == "http://controme.local/set/json/v1/1/temperaturszenen/2/"
        assert SESSION.posts[0]["data"] == {**expected, "user": USER, "password": PASSWORD}
        # Refresh delayed like for the temporary temperature
        assert [call["delay"] for call in ha_stubs.CALL_LATER] == [climate.DELAYED_REFRESH_SECONDS]
        assert coordinator.refreshes == 0


def test_activate_scene_rejections_send_nothing():
    cases = [
        (13, 1, LIVE_SCENES, "scene_not_single_room"),   # "*" with all 11 rooms
        (13, 99, LIVE_SCENES, "unknown_scene"),
        (3, 2, LIVE_SCENES, "scene_not_single_room"),    # scene 2 on another room
        (13, 2, None, "scene_list_unavailable"),         # GET failed
        (13, 2, [{"id": 2, "raeume": "x"}], "scene_list_unavailable"),
    ]
    for room_id, scene_id, scenes, key in cases:
        reset()
        entity, coordinator = make_scene_climate(room_id)
        SESSION.get_responses.append(FakeResponse(500) if scenes is None else FakeResponse(payload=scenes))
        err = raises(ha_stubs.HomeAssistantError, scene_call, entity, scene_id=scene_id)
        assert (err.translation_domain, err.translation_key) == ("controme", key), (room_id, scene_id)
        # Only an unreadable scene list is a Controme problem; the rest are user errors
        assert isinstance(err, ha_stubs.ServiceValidationError) == (key != "scene_list_unavailable"), key
        assert SESSION.posts == [], (room_id, scene_id)
        assert coordinator.refreshes == 0


def test_activate_scene_ambiguous_room_name():
    reset()
    entity, coordinator = make_scene_climate()
    # A second room with the same "Etage / Raum" label
    coordinator.data.append({"id": 60, "etagenname": "TEST (ssÜÖÄüöä)",
                             "raeume": [{"id": 14, "name": "testraum (ßüöäüöä)"}]})
    SESSION.get_responses.append(FakeResponse(payload=LIVE_SCENES))
    err = raises(ha_stubs.ServiceValidationError, scene_call, entity, scene_id=2)
    assert err.translation_key == "scene_room_ambiguous"
    assert SESSION.posts == []


def test_activate_scene_synthetic_room_and_unloaded_entry():
    reset()
    entity, _ = make_climate({"name": "Floor", "temperatur": 20.0})
    err = raises(ha_stubs.ServiceValidationError, scene_call, entity, scene_id=2)
    assert err.translation_key == "not_a_room"
    ha_stubs.UNLOADED_ENTRIES.add("entry1")
    try:
        entity, _ = make_scene_climate()
        err = raises(ha_stubs.ServiceValidationError, scene_call, entity, scene_id=2)
        assert err.translation_key == "service_config_entry_not_loaded"
    finally:
        ha_stubs.UNLOADED_ENTRIES.clear()
    assert SESSION.posts == [] and SESSION.gets == []


def test_activate_scene_applied_to_other_rooms():
    reset()
    ha_stubs.CALL_LATER.clear()
    LOGS.messages.clear()
    entity, _ = make_scene_climate()
    SESSION.get_responses.append(FakeResponse(payload=LIVE_SCENES))
    SESSION.post_responses.append(FakeResponse(
        200, '{"roomlist": {"1": 5.0, "2": 23.5, "13": 21.5, "77": 20.0}, "time": "17:01"}'))
    err = raises(ha_stubs.HomeAssistantError, scene_call, entity, scene_id=2)
    assert err.translation_key == "scene_applied_to_other_rooms"
    assert err.translation_placeholders == {
        "scene_id": "2", "rooms": "Etage 1 / Raum 1, Etage 2 / Raum 2, Room 77"}
    assert any("Etage 1 / Raum 1" in message for message in LOGS.messages)
    assert_no_credentials(err, err.translation_placeholders, *LOGS.messages)
    # The refresh is scheduled anyway, so the UI shows the real state
    assert len(ha_stubs.CALL_LATER) == 1


def test_activate_scene_roomlist_missing_only_logged():
    for body in ("", "not json", '{"time": "17:01"}', '{"roomlist": [13]}', "[1, 2]"):
        reset()
        entity, _ = make_scene_climate()
        SESSION.get_responses.append(FakeResponse(payload=LIVE_SCENES))
        SESSION.post_responses.append(FakeResponse(200, body))
        scene_call(entity, scene_id=2)
        assert len(SESSION.posts) == 1, body


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
    assert set(registered) == {"set_temporary_temperature", "activate_scene"}
    assert registered["activate_scene"]["entity_domain"] == "climate"
    assert registered["activate_scene"]["func"] == "async_activate_scene"
    # No scene entity platform
    assert "scene" not in [str(platform).lower() for platform in integration.PLATFORMS]


# S4b-02: pre-check of the scene list
TEST_LABEL = "Test (ßÜÖÄüöä) / Testraum (ßÜÖÄüöä)"
ALL_LABELS = [f"Etage {n} / Raum {n}" for n in range(1, 11)] + [TEST_LABEL]
STAR_SCENE = {"id": 1, "Name": "*", "raeume": [
    {"active": True, "temperatur": 21.0, "name": label} for label in ALL_LABELS]}
TEST_SCENE = {"id": 2, "Name": "HA-Test", "raeume": [
    {"active": False, "temperatur": 21.5, "name": TEST_LABEL}]}
LIVE_SCENES = [STAR_SCENE, TEST_SCENE]


def check_scene(scenes, scene_id, label=TEST_LABEL, labels=None):
    return helpers.check_scene_for_room(scenes, scene_id, label, ALL_LABELS if labels is None else labels)


def test_scene_check_single_room_ok():
    # "active": false does not matter, every listed room belongs to the scene
    assert check_scene(LIVE_SCENES, 2) is None
    assert check_scene([{"id": "2", "name": "lower", "raeume": TEST_SCENE["raeume"]}], 2) is None


def test_scene_check_star_scene_rejected():
    key, placeholders = check_scene(LIVE_SCENES, 1)
    assert key == "scene_not_single_room"
    assert placeholders["scene"] == "*" and placeholders["scene_id"] == "1"
    assert placeholders["rooms"].count(" / ") == 11


def test_scene_check_other_room_and_empty():
    assert check_scene(LIVE_SCENES, 2, label="Etage 1 / Raum 1")[0] == "scene_not_single_room"
    foreign = [{"id": 3, "Name": "Other", "raeume": [{"active": True, "name": "Etage 2 / Raum 2"}]}]
    assert check_scene(foreign, 3)[0] == "scene_not_single_room"
    empty = [{"id": 4, "Name": "Empty", "raeume": []}]
    assert check_scene(empty, 4) == ("scene_not_single_room", {"scene_id": "4", "scene": "Empty", "rooms": "-"})
    # A single room plus an inactive second room is still two rooms
    two = [{"id": 5, "Name": "Two", "raeume": [{"active": True, "name": TEST_LABEL},
                                                {"active": False, "name": "Etage 1 / Raum 1"}]}]
    assert check_scene(two, 5)[0] == "scene_not_single_room"


def test_scene_check_unknown_and_unreadable():
    assert check_scene(LIVE_SCENES, 99) == ("unknown_scene", {"scene_id": "99"})
    for scenes in (None, {}, "text", [{"id": 2, "Name": "x"}], [{"id": 2, "raeume": "x"}],
                   [{"id": 2, "raeume": [{"active": True}]}], [{"id": 2, "raeume": [None]}],
                   [{"id": 2, "raeume": [{"name": 13}]}], [TEST_SCENE, TEST_SCENE]):
        assert check_scene(scenes, 2) == ("scene_list_unavailable", {}), scenes
    assert check_scene([{"Name": "no id"}, {"id": True}, {"id": "x"}, None], 2)[0] == "unknown_scene"


def test_scene_check_names_normalized():
    import unicodedata
    decomposed = unicodedata.normalize("NFD", TEST_LABEL)
    variants = [decomposed, TEST_LABEL.upper(), "  Test (ßÜÖÄüöä)  /  Testraum   (ßÜÖÄüöä) "]
    for name in variants:
        scenes = [{"id": 2, "Name": "HA-Test", "raeume": [{"active": True, "name": name}]}]
        assert check_scene(scenes, 2) is None, name
    # casefold: "ß" equals "ss"
    assert check_scene(LIVE_SCENES, 2, label="test (ssüöäüöä) / testraum (ssüöäüöä)") is None


def test_scene_check_ambiguous_room_name():
    key, placeholders = check_scene(LIVE_SCENES, 2, labels=ALL_LABELS + [TEST_LABEL.lower()])
    assert key == "scene_room_ambiguous" and placeholders == {"room": TEST_LABEL}


def test_room_labels_from_temps():
    data = [{"id": 5, "etagenname": "Test (ßÜÖÄüöä)", "raeume": [{"id": 13, "name": "Testraum (ßÜÖÄüöä)"}]},
            {"id": 6, "raeume": [{"id": 14, "name": "Bad"}, {"id": 15}, None]}, None, {"id": 7, "raeume": "x"}]
    assert helpers.room_labels(data) == [(5, 13, TEST_LABEL), (6, 14, " / Bad")]


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
