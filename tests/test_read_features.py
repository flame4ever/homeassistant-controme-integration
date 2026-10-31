"""Offline tests for the read features of 2.4.0 and the entity ID snapshot (no Home Assistant).

Run with: python tests/test_read_features.py
"""
import asyncio
import copy
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
from custom_components.controme import binary_sensor, climate, helpers, sensor  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE_DATA = json.loads((FIXTURES / "temps.json").read_text(encoding="utf-8"))
# unique_id -> entity_id of all entities 2.3.0 created from snapshot_data()
SNAPSHOT_230 = json.loads((FIXTURES / "entity_ids_2.3.0.json").read_text(encoding="utf-8"))
BASE = "http://controme.local"


class FakeCoordinator:
    def __init__(self, data):
        self.data = data
        self.hass = object()
        self.last_update_success = True
        self.hub_device_id = "hub"
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1


def make_entry():
    return type("Entry", (), {"data": {"api_url": BASE, "haus_id": "1", "user": "u",
                                       "password": "p"}, "options": {},
                              "entry_id": "entry1"})()


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


def snapshot_data():
    """The fixture plus return sensors, a non-room sensor, umlauts, outputs and a room-less floor."""
    data = copy.deepcopy(FIXTURE_DATA)
    room10 = data[0]["raeume"][0]
    room10["sensoren"][1]["beschreibung"] = "Rücklauf Room 10"
    room10["sensoren"][2]["beschreibung"] = "LuftFeuchte Room 10"
    room10["ausgang"] = {"12": 99}
    room6 = data[1]["raeume"][0]
    room6["name"] = "Küche & Flur"
    room6["sensoren"][1]["beschreibung"] = "Room 6 RL"
    data.append({"id": 9, "etagenname": "Dach", "temperatur": 20.0, "solltemperatur": 19.0,
                 "raeume": []})
    return data


def collect_entities(data, coordinator=None):
    """Run the setup of all entity platforms and return the created entities."""
    coordinator = coordinator or FakeCoordinator(data)
    entry = make_entry()
    entry.runtime_data = coordinator
    entities = []
    for platform in (sensor, climate, binary_sensor):
        asyncio.run(platform.async_setup_entry(None, entry, entities.extend))
    return entities


def entity_ids(entities):
    """Return {unique_id: entity_id}; duplicate unique IDs fail."""
    ids = {}
    for entity in entities:
        assert entity._attr_unique_id not in ids, f"duplicate unique_id {entity._attr_unique_id}"
        ids[entity._attr_unique_id] = entity.entity_id
    return ids


# Snapshot: every unique_id and entity_id of 2.3.0 is unchanged, new IDs do not collide
def test_snapshot_existing_ids_unchanged():
    ids = entity_ids(collect_entities(snapshot_data()))
    missing = {uid: eid for uid, eid in SNAPSHOT_230.items() if ids.get(uid) != eid}
    assert not missing, missing
    new_entity_ids = [eid for uid, eid in ids.items() if uid not in SNAPSHOT_230]
    assert not set(new_entity_ids) & set(SNAPSHOT_230.values()), new_entity_ids
    assert len(set(ids.values())) == len(ids), "duplicate entity_id"


def by_unique_id(entities):
    return {entity._attr_unique_id: entity for entity in entities}


def room_sensor_entity(room, sensor_type, floor_id=5):
    """Return a ContromeSensor of the given type for room (dict with id) on floor_id."""
    room["floor_id"], room["room_id"] = floor_id, room.get("id")
    coordinator = FakeCoordinator([{"id": floor_id, "raeume": [room]}])
    return sensor.ContromeSensor(coordinator, make_entry(), room, sensor_type, {}), coordinator


# General: translations are valid JSON, en and de have the same keys, no control characters
def _keys(value, prefix=""):
    if isinstance(value, dict):
        keys = set()
        for key, child in value.items():
            keys.add(f"{prefix}{key}")
            keys |= _keys(child, f"{prefix}{key}.")
        return keys
    return set()


def _strings(value):
    if isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, str):
        yield value


def test_translations_same_keys_and_clean():
    folder = ha_stubs.ROOT / "custom_components" / "controme" / "translations"
    en = json.loads((folder / "en.json").read_text(encoding="utf-8"))
    de = json.loads((folder / "de.json").read_text(encoding="utf-8"))
    assert _keys(en) == _keys(de), _keys(en) ^ _keys(de)
    for text in list(_strings(en)) + list(_strings(de)):
        assert not any(ord(char) < 32 for char in text), repr(text)
    # Placeholders are the same in both languages
    import re
    for key in _keys(en):
        node_en, node_de = en, de
        for part in key.split("."):
            node_en, node_de = node_en[part], node_de[part]
        if isinstance(node_en, str):
            assert set(re.findall(r"{(\w+)}", node_en)) == set(re.findall(r"{(\w+)}", node_de)), key


def test_source_files_without_control_characters():
    package = ha_stubs.ROOT / "custom_components" / "controme"
    for path in list(package.glob("*.py")) + list(package.glob("*.yaml")) + list(package.glob("*.json")):
        text = path.read_text(encoding="utf-8")
        bad = [char for char in text if ord(char) < 32 and char not in "\n\r\t"]
        assert not bad, f"{path.name}: {bad!r}"
    json.loads((package / "manifest.json").read_text(encoding="utf-8"))


def test_new_sensor_types_translated():
    en = json.loads((ha_stubs.ROOT / "custom_components" / "controme" / "translations" / "en.json")
                    .read_text(encoding="utf-8"))
    for description in sensor.SENSOR_TYPES:
        assert description.translation_key in en["entity"]["sensor"], description.translation_key


# S6-01: control deviation
def test_control_deviation_live_examples():
    # Sportzimmer, Badezimmer and Eingang of the live system
    assert helpers.control_deviation({"temperatur": 21.44, "solltemperatur": 22.0, "total_offset": 0.1641}) == -0.40
    assert helpers.control_deviation({"temperatur": 23.0, "solltemperatur": 23.5, "total_offset": 0.1538}) == -0.35
    assert helpers.control_deviation({"temperatur": 21.94, "solltemperatur": 22.0, "total_offset": 0.143}) == 0.08


def test_control_deviation_offset_missing_or_invalid():
    assert helpers.control_deviation({"temperatur": 21.5, "solltemperatur": 22.0}) == -0.5
    assert helpers.control_deviation({"temperatur": "21.5", "solltemperatur": "22", "total_offset": "0.25"}) == -0.25
    for offset in (None, "abc", True, [], "nan"):
        assert helpers.control_deviation(
            {"temperatur": 21.5, "solltemperatur": 22.0, "total_offset": offset}) is None, offset


def test_control_deviation_current_or_target_missing():
    for room in ({"solltemperatur": 22.0}, {"temperatur": 21.0},
                 {"temperatur": None, "solltemperatur": 22.0},
                 {"temperatur": "kein Sensor vorhanden", "solltemperatur": 22.0},
                 {"temperatur": 21.0, "solltemperatur": False}, {}):
        assert helpers.control_deviation(room) is None, room


def test_control_deviation_entity():
    entity, coordinator = room_sensor_entity(
        {"id": 13, "name": "Testraum", "temperatur": 21.44, "solltemperatur": 22.0,
         "total_offset": 0.1641}, "control_deviation")
    assert entity._attr_unique_id == "1_5_13_control_deviation"
    assert entity.entity_id == "sensor.controme_testraum_control_deviation"
    assert entity._attr_native_value == -0.40 and entity.available
    description = entity.entity_description
    assert description.native_unit_of_measurement == "K"
    assert description.device_class is None
    assert description.state_class == "MEASUREMENT"
    assert description.suggested_display_precision == 2
    assert description.entity_registry_enabled_default is True
    # A non-numeric value makes the sensor unavailable
    coordinator.data[0]["raeume"][0]["temperatur"] = "kein Sensor vorhanden"
    entity._handle_coordinator_update()
    assert entity._attr_native_value is None and not entity.available


def test_control_deviation_only_with_current_and_target():
    data = [{"id": 1, "raeume": [
        {"id": 1, "name": "A", "temperatur": 21.0, "solltemperatur": 21.0},
        {"id": 2, "name": "B", "temperatur": 21.0},
        {"id": 3, "name": "C", "solltemperatur": 21.0, "total_offset": 0.5},
    ]}]
    ids = entity_ids(collect_entities(data))
    assert [uid for uid in ids if uid.endswith("_control_deviation")] == ["1_1_1_control_deviation"]


# S6-02: valve position
def test_outputs_keys_stripped_and_duplicates():
    assert helpers.normalize_outputs({"8": 0, " 6": 0, " 7": 0}) == {"8": 0, "6": 0, "7": 0}
    for value in ({}, None, [], "x", 5):
        assert helpers.normalize_outputs(value) == {}
    LOGS.messages.clear()
    assert helpers.normalize_outputs({" 6": 0, "6 ": 99, "7": 25}) == {"6": 99, "7": 25}
    assert any("reported twice" in message for message in LOGS.messages)


def test_valve_position_values():
    assert helpers.valve_position({}) is None
    assert helpers.valve_position({"1": 0, "2": 1}) == 0.5          # relay 0/1
    assert helpers.valve_position({"1": 1}) == 1.0
    assert helpers.valve_position({"1": 0, "2": 25, "3": 99}) == 41.33
    assert helpers.valve_position({"12": 99}) == 99.0
    # bool and non-numeric strings are ignored, numeric strings count
    assert helpers.valve_position({"1": True, "2": False, "3": 50}) == 50.0
    assert helpers.valve_position({"1": "an", "2": None, "3": "25"}) == 25.0
    assert helpers.valve_position({"1": True, "2": "aus", "3": "nan"}) is None


def test_valve_entity():
    room = {"id": 3, "name": "Badezimmer", "temperatur": 23.0, "ausgang": {" 3": 25, "4": 75}}
    entity, coordinator = room_sensor_entity(room, "valve")
    assert entity._attr_unique_id == "1_5_3_valve"
    assert entity.entity_id == "sensor.controme_badezimmer_valve"
    assert entity._attr_native_value == 50.0 and entity.available
    assert entity.extra_state_attributes["outputs"] == {"3": 25, "4": 75}
    description = entity.entity_description
    assert description.native_unit_of_measurement == "%"
    assert description.state_class == "MEASUREMENT"
    assert description.icon == "mdi:valve"
    assert description.entity_registry_enabled_default is False
    # /outs/ failed: no "ausgang" in the new data, so the sensor is unavailable
    coordinator.data = [{"id": 5, "raeume": [{"id": 3, "name": "Badezimmer"}]}]
    entity._handle_coordinator_update()
    assert not entity.available and entity.extra_state_attributes["outputs"] == {}


def test_valve_only_for_rooms_with_outputs():
    data = [{"id": 1, "raeume": [
        {"id": 1, "name": "A", "ausgang": {"9": 0}},
        {"id": 2, "name": "Flur OG", "ausgang": {}},
        {"id": 3, "name": "Testraum"},
        {"id": 4, "name": "D", "ausgang": [0]},
    ]}]
    ids = entity_ids(collect_entities(data))
    assert [uid for uid in ids if uid.endswith("_valve")] == ["1_1_1_valve"]


def test_hvac_action_unchanged_by_valve():
    # _hvac_action_from_outputs still uses the raw outputs (any value > 0 heats)
    room = {"id": 13, "name": "R", "betriebsart": "Heating", "ausgang": {" 6": 0, "7": 25}}
    room["floor_id"], room["room_id"] = 5, 13
    entity = climate.ContromeClimate(FakeCoordinator([{"id": 5, "raeume": [room]}]), make_entry(), room, {})
    assert entity._attr_hvac_action == ha_stubs.HVACAction.HEATING


# S6-03: further room sensors
def _sensor(description, name="26_8c_51_33_02_00_00_21", room_sensor=False, **extra):
    return {"raumtemperatursensor": room_sensor, "name": name, "wert": 55.2,
            "beschreibung": description, "letzte_uebertragung": "30.10.2026 15:10", **extra}


def test_room_sensor_classification():
    classify = helpers.classify_room_sensor
    assert classify(_sensor("LuftFeuchte Sportzimmer")) == "humidity"
    assert classify(_sensor("Humidity kitchen")) == "humidity"
    assert classify(_sensor("Luftfeuchte Küche (ÄÖÜß)")) == "humidity"
    assert classify(_sensor("Temperatur Wintergarten")) == "temperature"
    assert classify(_sensor("Funk-Temp Büro")) == "temperature"
    assert classify(_sensor("outdoor temperature")) == "temperature"
    # Unknown or ambiguous descriptions are skipped, nothing is guessed
    for description in ("Sensor 2 Room 10", "CO2 Bad", "", None, 5, "Temp/Feuchte Kombi"):
        assert classify(_sensor(description)) is None, description


def test_room_sensor_room_temperature_and_return_excluded():
    classify = helpers.classify_room_sensor
    assert classify(_sensor("RaumTemp Bad", room_sensor=True)) is None
    assert classify(_sensor("RaumTemp Bad", room_sensor="true")) is None
    for description in ("Rücklauf Bad", "Galerie RL", "Return temperature kitchen", "RL Feuchte"):
        assert classify(_sensor(description)) is None, description
    for name in (None, "", "  ", 7):
        assert classify(_sensor("LuftFeuchte Bad", name=name)) is None, name
    assert classify("not a sensor") is None


def test_room_sensor_entities():
    room = {"id": 4, "name": "Küche", "temperatur": 21.0, "sensoren": [
        _sensor("RaumTemp Küche", name="28_01", room_sensor=True),
        _sensor("Rücklauf Küche", name="28_02"),
        _sensor("LuftFeuchte Küche", name="26_8c_51_33_02_00_00_21"),
        _sensor("Funkthermometer Temp", name="VSensor*2", wert="19.5"),
        _sensor("Sensor 9", name="28_09"),
        _sensor("LuftFeuchte doppelt", name="26_8c_51_33_02_00_00_21"),
    ]}
    LOGS.messages.clear()
    entities = by_unique_id(collect_entities([{"id": 2, "raeume": [room]}]))
    room_sensors = {uid: entity for uid, entity in entities.items() if "_sensor_" in uid}
    assert set(room_sensors) == {"1_2_4_sensor_26_8c_51_33_02_00_00_21", "1_2_4_sensor_VSensor*2"}
    # Return sensor and room temperature keep their own entities
    assert "1_2_4_return_28_02" in entities and "1_2_4_current" in entities
    humidity = room_sensors["1_2_4_sensor_26_8c_51_33_02_00_00_21"]
    assert humidity.entity_id == "sensor.controme_kuche_sensor_26_8c_51_33_02_00_00_21"
    assert humidity.entity_description.translation_key == "room_sensor"
    assert humidity.entity_description.device_class == "HUMIDITY"
    assert humidity.entity_description.native_unit_of_measurement == "%"
    assert humidity.entity_description.entity_registry_enabled_default is False
    assert humidity._attr_translation_placeholders == {"sensor": "LuftFeuchte Küche"}
    assert humidity._attr_native_value == 55.2
    assert humidity.extra_state_attributes["sensor_id"] == "26_8c_51_33_02_00_00_21"
    assert humidity.extra_state_attributes["last_transmission"] == "2026-10-30T15:10:00+01:00"
    temperature = room_sensors["1_2_4_sensor_VSensor*2"]
    assert temperature.entity_id == "sensor.controme_kuche_sensor_vsensor_2"
    assert temperature.entity_description.device_class == "TEMPERATURE"
    assert temperature.entity_description.native_unit_of_measurement == "CELSIUS"
    assert temperature.entity_description.entity_registry_enabled_default is False
    assert temperature._attr_native_value == 19.5
    assert any("Sensor 9" in message for message in LOGS.messages)
    assert any("LuftFeuchte doppelt" in message for message in LOGS.messages)


def test_room_sensor_update_and_removal():
    room = {"id": 4, "name": "Bad", "sensoren": [_sensor("LuftFeuchte Bad", name="26_01")]}
    entity, coordinator = room_sensor_entity(room, "sensor_26_01")
    assert entity.available and entity._attr_native_value == 55.2
    new_room = {"id": 4, "name": "Bad", "sensoren": [
        _sensor("LuftFeuchte Bad", name="26_01", wert="kein Sensor vorhanden",
                letzte_uebertragung="31.10.2026 08:00")]}
    coordinator.data = [{"id": 5, "raeume": [new_room]}]
    entity._handle_coordinator_update()
    assert not entity.available
    assert entity.extra_state_attributes["last_transmission"] == "2026-10-31T08:00:00+01:00"
    coordinator.data = [{"id": 5, "raeume": [{"id": 4, "name": "Bad", "sensoren": []}]}]
    entity._handle_coordinator_update()
    assert not entity.available


def test_room_sensor_prefix_never_collides_with_return():
    # The same Controme name as return and as further sensor gives different IDs
    room = {"id": 4, "name": "Bad", "sensoren": [
        _sensor("Rücklauf Bad", name="28_01"), _sensor("LuftFeuchte Bad", name="return_28_01"),
        _sensor("Temperatur Bad", name="28_01x")]}
    ids = entity_ids(collect_entities([{"id": 2, "raeume": [room]}]))
    assert "1_2_4_return_28_01" in ids
    assert "1_2_4_sensor_return_28_01" in ids
    assert all(uid.startswith("1_2_4_") for uid in ids if "_sensor_" in uid)
    # The snapshot keeps all 2.3.0 IDs; its only new room sensor is the humidity one
    new = set(entity_ids(collect_entities(snapshot_data()))) - set(SNAPSHOT_230)
    assert "1_1_10_sensor_28_00_00_00_00_00_00_03" in new
    assert not any(uid.startswith("1_1_10_sensor_28_00_00_00_00_00_00_02") for uid in new)


# S6-05: hub sw_version/hw_version from /info/
SESSION = ha_stubs.SESSION
FakeResponse = ha_stubs.FakeResponse


def reset_session():
    SESSION.posts.clear()
    SESSION.gets.clear()
    SESSION.get_timeouts.clear()
    SESSION.post_responses.clear()
    SESSION.get_responses.clear()


def test_hub_versions_parsing():
    assert helpers.hub_versions({}) == {}
    for info in (None, [], "x", {"sw-date": "", "hw": "  "}, {"sw-date": True, "hw": None},
                 {"branch": "stable"}):
        assert helpers.hub_versions(info) == {}, info
    assert helpers.hub_versions({"hw": "pi4", "sw-date": "2026-02-25", "branch": "stable_v2",
                                 "os": "x", "fbi": 1}) == {
        "sw_version": "2026-02-25 (stable_v2)", "hw_version": "pi4"}
    assert helpers.hub_versions({"sw-date": "2026-02-25"}) == {"sw_version": "2026-02-25"}
    assert helpers.hub_versions({"sw-date": 20260225, "branch": ""}) == {"sw_version": "20260225"}
    assert helpers.hub_versions({"hw": "pi3"}) == {"hw_version": "pi3"}


def test_hub_versions_request_never_fails():
    cases = [
        (FakeResponse(payload={}), {}),
        (FakeResponse(payload={"hw": "pi4", "sw-date": "2026-02-25", "branch": "stable"}),
         {"sw_version": "2026-02-25 (stable)", "hw_version": "pi4"}),
        (TimeoutError(), {}),
        (ha_stubs.ClientError("boom"), {}),
        (FakeResponse(payload=ValueError("no JSON")), {}),
        (FakeResponse(500), {}),
        (FakeResponse(payload=["x"]), {}),
    ]
    for response, expected in cases:
        reset_session()
        SESSION.get_responses.append(response)
        assert asyncio.run(integration.async_get_hub_versions(None, BASE + "/", "1")) == expected
        assert SESSION.gets == ["http://controme.local/get/json/v1/1/info/"]
        assert SESSION.get_timeouts[0].total == 5
        assert SESSION.posts == []


class FakeDeviceRegistry:
    def __init__(self):
        self.calls = []

    def async_get_or_create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Device", (), {"id": "hub-device"})()


def run_setup_entry(info_response):
    """Run async_setup_entry with a fake coordinator and device registry; return the registry."""
    registry = FakeDeviceRegistry()
    device_registry_module = sys.modules["homeassistant.helpers.device_registry"]

    class SetupCoordinator(FakeCoordinator):
        def __init__(self, hass, entry, base_url, house_id):
            super().__init__(FIXTURE_DATA)

        async def async_config_entry_first_refresh(self):
            pass

    class ConfigEntries:
        async def async_forward_entry_setups(self, entry, platforms):
            self.forwarded = platforms

    entry = make_entry()
    entry.add_update_listener = lambda listener: None
    entry.async_on_unload = lambda func: None
    hass = type("Hass", (), {"config_entries": ConfigEntries()})()
    original = integration.ContromeDataUpdateCoordinator, getattr(device_registry_module, "async_get")
    integration.ContromeDataUpdateCoordinator = SetupCoordinator
    device_registry_module.async_get = lambda hass: registry
    reset_session()
    SESSION.get_responses.append(info_response)
    try:
        assert asyncio.run(integration.async_setup_entry(hass, entry)) is True
    finally:
        integration.ContromeDataUpdateCoordinator, device_registry_module.async_get = original
    assert entry.runtime_data.hub_device_id == "hub-device"
    return registry


def test_setup_entry_with_and_without_info():
    base = {"config_entry_id": "entry1", "identifiers": {("controme", "1")}, "manufacturer": "Controme",
            "name": "Controme Home 1", "model": "Thermostat API"}
    # {} (live), errors and broken JSON: the hub device is created exactly as in 2.3.0
    for response in (FakeResponse(payload={}), TimeoutError(), FakeResponse(payload=ValueError("x")),
                     ha_stubs.ClientError("x")):
        registry = run_setup_entry(response)
        assert registry.calls == [base], response
    registry = run_setup_entry(FakeResponse(payload={"hw": "pi4", "sw-date": "2026-02-25"}))
    assert registry.calls == [{**base, "sw_version": "2026-02-25", "hw_version": "pi4"}]


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
    print(f"{len(tests) - failures - skipped}/{len(tests)} tests passed, {skipped} skipped")
    return failures


if __name__ == "__main__":
    sys.exit(1 if run(dict(globals())) else 0)
