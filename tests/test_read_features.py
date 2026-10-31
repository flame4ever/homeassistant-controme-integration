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
