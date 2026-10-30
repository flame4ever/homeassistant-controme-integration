"""Offline tests for the transmission monitoring helpers (no Home Assistant needed).

Run with: python tests/test_transmission.py
Home Assistant and aiohttp are replaced by small stubs, the fixture is an anonymized
/temps/ dump of a real Controme system.
"""
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "temps.json"
# Fixed offset instead of a ZoneInfo, so the tests need no tzdata package
TIME_ZONE = timezone(timedelta(hours=1))


def _load_helpers():
    """Import helpers.py with stubbed homeassistant.util.dt and aiohttp."""
    dt_stub = types.ModuleType("homeassistant.util.dt")
    dt_stub.get_default_time_zone = lambda: TIME_ZONE
    util_stub = types.ModuleType("homeassistant.util")
    util_stub.dt = dt_stub
    sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
    sys.modules["homeassistant.util"] = util_stub
    sys.modules["homeassistant.util.dt"] = dt_stub
    sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
    spec = importlib.util.spec_from_file_location(
        "controme_helpers", ROOT / "custom_components" / "controme" / "helpers.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


helpers = _load_helpers()
FIXTURE_DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
SENSOR_COUNT = sum(
    len(room.get("sensoren") or []) for floor in FIXTURE_DATA for room in floor.get("raeume") or []
)


def local(*args):
    """Return a datetime in the test time zone."""
    return datetime(*args, tzinfo=TIME_ZONE)


def test_parse_all_formats():
    assert helpers.parse_transmission("30.10.2026 15:10") == local(2026, 10, 30, 15, 10)
    assert helpers.parse_transmission("30.10.2026 15:10:19") == local(2026, 10, 30, 15, 10, 19)
    assert helpers.parse_transmission("15:10:19 30.10.2026") == local(2026, 10, 30, 15, 10, 19)
    assert helpers.parse_transmission("15:10 30.10.2026") == local(2026, 10, 30, 15, 10)
    assert helpers.parse_transmission(" 22.03.2025 20:48 ") == local(2025, 3, 22, 20, 48)
    assert helpers.parse_transmission("30.10.2026 15:10").tzinfo is TIME_ZONE


def test_parse_none_and_garbage():
    for value in (None, "", "   ", "kein Sensor vorhanden", "32.13.2026 10:00",
                  "30.10.2026", "2026-10-30T15:10:00", 1730297400, 15.1, ["30.10.2026 15:10"]):
        assert helpers.parse_transmission(value) is None, value


def test_age_future_is_zero():
    now = local(2026, 10, 30, 15, 0)
    assert helpers.transmission_age(local(2026, 10, 30, 15, 5), now) == timedelta(0)
    assert helpers.transmission_age(local(2026, 10, 30, 14, 45), now) == timedelta(minutes=15)


def test_fixture_fresh():
    newest, count, stale = helpers.collect_stale(
        FIXTURE_DATA, local(2026, 10, 30, 15, 12), timedelta(minutes=15)
    )
    assert newest == local(2026, 10, 30, 15, 12)
    assert (count, stale) == (0, [])


def test_threshold_boundary():
    threshold = timedelta(minutes=15)
    # Exactly at the threshold the 15:10 sensors are not stale yet
    _newest, count, _stale = helpers.collect_stale(FIXTURE_DATA, local(2026, 10, 30, 15, 25), threshold)
    assert count == 0
    # One second later all sensors except the one from 15:12 are stale
    _newest, count, stale = helpers.collect_stale(FIXTURE_DATA, local(2026, 10, 30, 15, 25, 1), threshold)
    assert count == SENSOR_COUNT - 1
    assert len(stale) == min(count, helpers.MAX_STALE_SENSORS)


def test_list_limited_to_20_and_oldest_first():
    data = copy.deepcopy(FIXTURE_DATA)
    sensors = [sensor for floor in data for room in floor["raeume"] for sensor in room["sensoren"]]
    for minute, sensor in enumerate(sensors):
        sensor["letzte_uebertragung"] = f"30.10.2026 10:{minute:02d}"
    newest, count, stale = helpers.collect_stale(data, local(2026, 10, 30, 23, 0), timedelta(minutes=15))
    assert SENSOR_COUNT > helpers.MAX_STALE_SENSORS
    assert count == SENSOR_COUNT
    assert len(stale) == helpers.MAX_STALE_SENSORS == 20
    assert newest == local(2026, 10, 30, 10, SENSOR_COUNT - 1)
    assert stale[0]["last_transmission"] == local(2026, 10, 30, 10, 0).isoformat()
    assert [entry["last_transmission"] for entry in stale] == sorted(entry["last_transmission"] for entry in stale)
    assert set(stale[0]) == {"room", "sensor", "name", "last_transmission"}
    assert stale[0]["room"] == data[0]["raeume"][0]["name"]
    assert stale[0]["name"] == sensors[0]["name"]
    assert stale[0]["sensor"] == sensors[0]["beschreibung"]


def test_unparseable_and_future_never_stale():
    data = copy.deepcopy(FIXTURE_DATA)
    sensors = [sensor for floor in data for room in floor["raeume"] for sensor in room["sensoren"]]
    sensors[0]["letzte_uebertragung"] = None
    sensors[1]["letzte_uebertragung"] = "kein Sensor vorhanden"
    sensors[2].pop("letzte_uebertragung")
    sensors[3]["letzte_uebertragung"] = "31.12.2030 12:00"
    room = data[0]["raeume"][0]
    room["sensoren"].append("not a sensor")
    newest, count, stale = helpers.collect_stale(data, local(2026, 10, 30, 16, 0), timedelta(minutes=15))
    assert newest == local(2030, 12, 31, 12, 0)
    # All sensors with a past timestamp are stale, the four special ones are not
    assert count == SENSOR_COUNT - 4
    names = {entry["name"] for entry in stale}
    assert not names & {sensor["name"] for sensor in sensors[:4]}


def test_empty_data():
    now = local(2026, 10, 30, 16, 0)
    for data in (None, [], [{"id": 1, "raeume": []}], [{"id": 1, "raeume": [{"id": 2}]}]):
        assert helpers.collect_stale(data, now, timedelta(minutes=15)) == (None, 0, [])


if __name__ == "__main__":
    failures = 0
    tests = [(name, func) for name, func in sorted(globals().items()) if name.startswith("test_")]
    for name, func in tests:
        try:
            func()
            print(f"OK   {name}")
        except AssertionError as err:
            failures += 1
            print(f"FAIL {name}: {err!r}")
    print(f"{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
