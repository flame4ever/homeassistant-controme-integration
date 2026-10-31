"""Helper functions for Controme integration."""
import asyncio
import math
import re
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import socket
import unicodedata
import aiohttp
from ipaddress import IPv4Network, IPv4Interface
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Formats of "letzte_uebertragung": /temps/ uses "30.10.2026 15:10", /rltemps/ "15:10:19 30.10.2026"
TRANSMISSION_FORMATS = (
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%H:%M:%S %d.%m.%Y",
    "%H:%M %d.%m.%Y",
)
# Maximum number of stale sensors listed in attributes
MAX_STALE_SENSORS = 20

def iter_rooms(data: Optional[List[Dict[str, Any]]]):
    """Yield (floor_id, room_id, room) for all rooms, using room-less floors as rooms."""
    for floor in data or []:
        floor_id = floor.get("id")
        rooms = floor.get("raeume") or []
        if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
            rooms = [floor]
        for index, room in enumerate(rooms):
            room_id = room.get("id")
            if room_id is None:
                room_id = f"{floor_id}_{index}"
            yield floor_id, room_id, room

def find_room(data: Optional[List[Dict[str, Any]]], floor_id: Any, room_id: Any) -> Optional[Dict[str, Any]]:
    """Return the room data for the given floor and room ID, or None if it is gone."""
    for current_floor_id, current_room_id, room in iter_rooms(data):
        if current_floor_id == floor_id and current_room_id == room_id:
            return room
    return None

def normalize_label(value: Any) -> str:
    """Normalize an "Etage / Raum" label for comparison (NFC, single spaces, casefold)."""
    return " ".join(unicodedata.normalize("NFC", str(value)).split()).casefold()

def room_labels(data: Optional[List[Dict[str, Any]]]) -> List[tuple]:
    """Return (floor_id, room_id, "Etage / Raum") for all rooms, like the scene list names them."""
    labels = []
    for floor in data or []:
        if not isinstance(floor, dict):
            continue
        rooms = floor.get("raeume")
        for room in rooms if isinstance(rooms, list) else []:
            if isinstance(room, dict) and room.get("name") is not None:
                labels.append((floor.get("id"), room.get("id"),
                               f"{floor.get('etagenname', '')} / {room.get('name')}"))
    return labels

def check_scene_for_room(
    scenes: Any, scene_id: int, target_label: str, all_labels: List[str]
) -> Optional[tuple]:
    """Check that a scene contains exactly the target room; return None or (error key, placeholders).

    Every room listed in the scene belongs to it, "active" only tells whether the
    scene is currently applied there. Rooms switched off in a scene are not listed.
    Allowed is only a scene with exactly one listed room whose "Etage / Raum" label
    matches the target room, and that label must be unique among all rooms.

    Controme ignores room_id for scenes and applies them to every listed room,
    so this check is the only protection of other rooms: never relax it.
    """
    if not isinstance(scenes, list):
        return "scene_list_unavailable", {}
    matches = []
    for scene in scenes:
        if not isinstance(scene, dict) or isinstance(scene.get("id"), bool):
            continue
        try:
            if int(scene.get("id")) == scene_id:
                matches.append(scene)
        except (TypeError, ValueError):
            continue
    if not matches:
        return "unknown_scene", {"scene_id": str(scene_id)}
    if len(matches) > 1:
        return "scene_list_unavailable", {}
    scene = matches[0]
    rooms = scene.get("raeume")
    if not isinstance(rooms, list) or not all(
        isinstance(room, dict) and isinstance(room.get("name"), str) for room in rooms
    ):
        return "scene_list_unavailable", {}
    scene_name = str(scene.get("Name") or scene.get("name") or scene_id)
    names = [room["name"] for room in rooms]
    placeholders = {
        "scene_id": str(scene_id),
        "scene": scene_name,
        "rooms": ", ".join(names) or "-",
    }
    target = normalize_label(target_label)
    if len(names) != 1 or normalize_label(names[0]) != target:
        return "scene_not_single_room", placeholders
    if [normalize_label(label) for label in all_labels].count(target) != 1:
        return "scene_room_ambiguous", {"room": target_label}
    return None

def is_synthetic_room(data: Optional[List[Dict[str, Any]]], room: Dict[str, Any]) -> bool:
    """Return True if the room has no own room ID (room-less floor or room without ID)."""
    return room.get("id") is None or any(floor is room for floor in data or [])

# Return sensors are described e.g. as "Rücklauf Bad", "Galerie RL" or "Return Kitchen"
def is_return_sensor(description: Optional[str]) -> bool:
    """Return True if a sensor description names a return flow (Rücklauf) sensor."""
    if not description:
        return False
    # The abbreviation "RL" is only matched as a separate word in capitals
    if re.search(r"\bRL\b", description):
        return True
    return re.search(r"rücklauf|\breturn\b", description, re.IGNORECASE) is not None

# Further room sensors are only created if their description clearly names the quantity
ROOM_SENSOR_HUMIDITY = re.compile(r"feuchte|humid", re.IGNORECASE)
# "temp" also matches "Temperatur" and "temperature"
ROOM_SENSOR_TEMPERATURE = re.compile(r"temp", re.IGNORECASE)
ROOM_SENSOR_KIND_HUMIDITY = "humidity"
ROOM_SENSOR_KIND_TEMPERATURE = "temperature"

def classify_room_sensor(sensor: Any) -> Optional[str]:
    """Return "humidity" or "temperature" for a further sensor of a room, else None.

    The room temperature sensor (its value is "temperatur") and return sensors
    have their own entities. Descriptions that match both or neither quantity are
    not classified, nothing is guessed.
    """
    if not isinstance(sensor, dict):
        return None
    name = sensor.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    room_sensor = sensor.get("raumtemperatursensor")
    if room_sensor is True or (isinstance(room_sensor, str) and room_sensor.strip().lower() == "true"):
        return None
    description = sensor.get("beschreibung")
    if not isinstance(description, str) or is_return_sensor(description):
        return None
    humidity = ROOM_SENSOR_HUMIDITY.search(description) is not None
    temperature = ROOM_SENSOR_TEMPERATURE.search(description) is not None
    if humidity and not temperature:
        return ROOM_SENSOR_KIND_HUMIDITY
    if temperature and not humidity:
        return ROOM_SENSOR_KIND_TEMPERATURE
    return None

def to_float(value: Any) -> Optional[float]:
    """Convert an API value to float, returning None for missing or non-numeric values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def control_deviation(room: Dict[str, Any]) -> Optional[float]:
    """Return temperatur - solltemperatur + total_offset in K (2 decimals), negative = too cold.

    A missing total_offset counts as 0; a present but non-numeric one gives None,
    like a non-numeric current or target temperature.
    """
    current = to_float(room.get("temperatur"))
    target = to_float(room.get("solltemperatur"))
    offset = to_float(room["total_offset"]) if "total_offset" in room else 0.0
    if current is None or target is None or offset is None:
        return None
    deviation = current - target + offset
    # "nan" or "inf" strings are numeric for float(), but no usable reading
    return round(deviation, 2) if math.isfinite(deviation) else None

def normalize_outputs(ausgang: Any) -> Dict[str, Any]:
    """Return the outputs of a room with stripped keys (/outs/ reports e.g. " 6").

    If two keys are equal after stripping, the last one wins.
    """
    if not isinstance(ausgang, dict):
        return {}
    outputs = {}
    for key, value in ausgang.items():
        stripped = str(key).strip()
        if stripped in outputs:
            _LOGGER.debug("Output %r reported twice after stripping, using the last value", stripped)
        outputs[stripped] = value
    return outputs

def valve_position(outputs: Dict[str, Any]) -> Optional[float]:
    """Return the mean of the numeric output values (2 decimals), or None without any.

    Booleans and non-numeric values are ignored. On relay systems the values are 0/1.
    """
    values = [to_float(value) for value in outputs.values()]
    values = [value for value in values if value is not None and math.isfinite(value)]
    if not values:
        return None
    return round(sum(values) / len(values), 2)

def parse_transmission(value: Any) -> Optional[datetime]:
    """Parse a Controme transmission timestamp, returning None for empty or unknown values.

    Controme reports local time without a time zone, so the Home Assistant time zone is
    assumed. In the repeated hour of the DST change the first occurrence is used.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    for time_format in TRANSMISSION_FORMATS:
        try:
            parsed = datetime.strptime(value.strip(), time_format)
        except ValueError:
            continue
        return parsed.replace(tzinfo=dt_util.get_default_time_zone())
    return None

def parse_mode_end(value: Any) -> Optional[datetime]:
    """Parse "mode_end_datetime" ("YYYY-MM-DD HH:MM:SS", local time) as aware datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=dt_util.get_default_time_zone())

def transmission_age(timestamp: datetime, now: datetime) -> timedelta:
    """Return the age of a transmission, timestamps in the future have age 0."""
    return max(now - timestamp, timedelta(0))

def collect_stale(
    data: Optional[List[Dict[str, Any]]], now: datetime, threshold: timedelta
) -> tuple[Optional[datetime], int, List[Dict[str, Any]]]:
    """Return the newest transmission, the number and a list of stale sensors.

    A sensor is stale if its last transmission is older than the threshold. Sensors
    without a parseable timestamp are never stale. The list holds the oldest
    MAX_STALE_SENSORS sensors.
    """
    newest = None
    stale = []
    for _floor_id, room_id, room in iter_rooms(data):
        for sensor in room.get("sensoren") or []:
            if not isinstance(sensor, dict):
                continue
            timestamp = parse_transmission(sensor.get("letzte_uebertragung"))
            if timestamp is None:
                continue
            if newest is None or timestamp > newest:
                newest = timestamp
            if transmission_age(timestamp, now) > threshold:
                stale.append((timestamp, {
                    "room": room.get("name") or f"Room {room_id}",
                    "sensor": sensor.get("beschreibung"),
                    "name": sensor.get("name"),
                    "last_transmission": timestamp.isoformat(),
                }))
    stale.sort(key=lambda item: item[0])
    return newest, len(stale), [entry for _timestamp, entry in stale[:MAX_STALE_SENSORS]]

def get_local_ip() -> Optional[str]:
    """Get the local IP address of the machine."""
    try:
        # Create a socket and connect to a known public address
        # This won't actually establish a connection but gives us the local IP
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        local_ip = sock.getsockname()[0]
        sock.close()
        _LOGGER.debug("Local IP detected: %s", local_ip)
        return local_ip
    except Exception as err:
        _LOGGER.error("Error getting local IP: %s", err)
        return None

def get_network_from_ip(ip: str) -> Optional[str]:
    """Get the network address from an IP address."""
    try:
        # Assume a /24 network
        interface = IPv4Interface(f"{ip}/24")
        network_str = str(interface.network)
        _LOGGER.debug("Network determined from IP %s: %s", ip, network_str)
        return network_str
    except Exception as err:
        _LOGGER.error("Error determining network from IP %s: %s", ip, err)
        return None

async def test_controme_host(session: aiohttp.ClientSession, ip: str) -> Optional[Dict[str, str]]:
    """Test if the given IP is a Controme system by checking the login page."""
    # Only check the specific login page URL
    login_url = f"http://{ip}/accounts/m_login/"
    
    try:
        # Check the login page with a short timeout
        async with asyncio.timeout(1):
            async with session.get(login_url) as response:
                if response.status == 200:
                    # Check for the specific title in the HTML
                    text = await response.text()
                    if "<title>Smart-Heat-OS - Login</title>" in text:
                        _LOGGER.info("Found Controme system at %s", ip)
                        return {"url": ip, "title": f"Controme at {ip}"}
    except (TimeoutError, aiohttp.ClientError, ValueError):
        # Skip hosts that do not answer or do not return a readable page
        pass
    
    return None

async def scan_network(networks: List[str] = None) -> List[Dict[str, str]]:
    """Scan network for Controme systems and stop after finding one."""
    start_time = asyncio.get_event_loop().time()
    
    if networks is None:
        # Get local network from Home Assistant's IP
        local_ip = get_local_ip()
        if local_ip:
            network = get_network_from_ip(local_ip)
            if network:
                _LOGGER.info("Detected local network: %s", network)
                networks = [network]
            else:
                _LOGGER.warning("Could not determine local network, using default networks")
                networks = ["192.168.1.0/24"]
        else:
            _LOGGER.warning("Could not determine local IP, using default networks")
            networks = ["192.168.1.0/24"]
    
    # Optimize connection settings for faster scanning
    connector = aiohttp.TCPConnector(limit_per_host=10, limit=100)
    timeout = aiohttp.ClientTimeout(total=30)
    
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        for network in networks:
            _LOGGER.info("Scanning network %s for Controme systems", network)
            
            try:
                # Create a single list of all IPs to scan
                all_ips = []
                
                # Prioritize some common IPs first
                priority_ips = [
                    "192.168.1.100",
                    "192.168.1.200",
                    "192.168.1.10",
                    "192.168.1.20",
                    "192.168.0.100",
                    "192.168.0.200"
                ]
                
                try:
                    ip_network = IPv4Network(network)
                    local_ip = get_local_ip()
                    
                    # Add all IPs to the list, prioritizing common ones
                    for ip in ip_network.hosts():
                        ip_str = str(ip)
                        if ip_str == local_ip:
                            continue  # Skip local IP
                        
                        if ip_str in priority_ips:
                            # Add priority IPs to the beginning
                            all_ips.insert(0, ip_str)
                        else:
                            # Add regular IPs to the end
                            all_ips.append(ip_str)
                except ValueError:
                    _LOGGER.error("Invalid network format: %s", network)
                    continue
                
                # Optimize chunk size for faster scanning
                chunk_size = 40
                
                # Process all IPs in a single pass with optimized chunks
                for i in range(0, len(all_ips), chunk_size):
                    chunk_ips = all_ips[i:i + chunk_size]
                    _LOGGER.debug("Scanning IPs %d to %d of %d", 
                                 i, min(i+chunk_size, len(all_ips)), len(all_ips))
                    
                    # Create tasks for this chunk
                    chunk_tasks = [test_controme_host(session, ip) for ip in chunk_ips]
                    
                    # Run all tasks in parallel
                    chunk_results = await asyncio.gather(*chunk_tasks, return_exceptions=True)
                    
                    # Process results
                    discovered_systems = []
                    for ip, result in zip(chunk_ips, chunk_results):
                        if isinstance(result, Exception):
                            continue
                        if result:
                            discovered_systems.append(result)
                            _LOGGER.info("Found Controme system: %s", result["url"])
                    
                    # If we found any systems, return immediately
                    if discovered_systems:
                        end_time = asyncio.get_event_loop().time()
                        scan_duration = end_time - start_time
                        _LOGGER.info("Network scan completed in %.2f seconds. Found %d Controme systems", 
                                   scan_duration, len(discovered_systems))
                        return discovered_systems
                
            except Exception as e:
                _LOGGER.error("Error scanning network %s: %s", network, str(e))
                continue
    
    # If we get here, no systems were found
    end_time = asyncio.get_event_loop().time()
    scan_duration = end_time - start_time
    _LOGGER.info("Network scan completed in %.2f seconds. No Controme systems found", scan_duration)
    return [] 