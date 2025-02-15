"""Platform for Controme sensor integration.

Diese Plattform ruft die API ab (basierend auf der konfigurierten Haus-ID) und importiert
die Räume als Geräte. Für jeden Raum werden separate Sensoren (z. B. aktuelle Temperatur 
und Solltemperatur) als Entitäten in dem zugehörigen Gerät erstellt.
"""

import logging
import aiohttp

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the Controme sensor platform."""
    sensors = []
    base_url = entry.data.get(CONF_API_URL).strip()
    if not (base_url.startswith("http://") or base_url.startswith("https://")):
        base_url = f"http://{base_url}"
    base_url = base_url.rstrip("/")
    house_id = entry.data.get(CONF_HAUS_ID)

    endpoint = f"{base_url}/get/json/v1/{house_id}/temps/"
    session = hass.helpers.aiohttp_client.async_get_clientsession()
    try:
        async with session.get(endpoint) as response:
            if response.status != 200:
                _LOGGER.error("Error fetching floors for sensors, status %s", response.status)
                return
            data = await response.json()
    except Exception as ex:
        _LOGGER.exception("Exception during fetching sensor data: %s", ex)
        return

    # Durchlaufe alle Etagen (floors) und sammle die Räume (raeume)
    for floor in data:
        floor_id = floor.get("id")
        floor_name = floor.get("etagenname", f"Floor {floor_id}")
        rooms = floor.get("raeume", [])
        # Falls keine Räume unter "raeume" vorhanden sind, aber direkt Sensorwerte geliefert werden,
        # dann wird angenommen, dass der Floor-Eintrag selbst die Raumdaten enthält.
        if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
            _LOGGER.debug("No 'raeume' found for floor %s, assuming floor is a room", floor_id)
            rooms = [floor]
        for index, room in enumerate(rooms):
            room_id = room.get("id")
            if not room_id:
                room_id = f"{floor_id}_{index}"
            # Verwende den im Raum definierten Namen oder einen generischen Namen
            room_name = room.get("name", f"Room {room_id}")

            # Erstelle device_info für den Raum (wird als Gerät in HA angezeigt)
            device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{house_id}_{room_id}")},
                name=room_name,
                manufacturer="Controme",
                model="Room Sensor",
            )

            # Erstelle Sensor-Entitäten. Zusätzlich werden die kompletten Raumdaten (room_data) übergeben.
            if room.get("temperatur") is not None:
                sensors.append(
                    ContromeRoomSensor(
                        base_url=base_url,
                        house_id=house_id,
                        floor_id=floor_id,
                        room_id=room_id,
                        room_name=room_name,
                        sensor_type="current",
                        initial_value=room.get("temperatur"),
                        device_info=device_info,
                        room_data=room,
                    )
                )
            if room.get("solltemperatur") is not None:
                sensors.append(
                    ContromeRoomSensor(
                        base_url=base_url,
                        house_id=house_id,
                        floor_id=floor_id,
                        room_id=room_id,
                        room_name=room_name,
                        sensor_type="target",
                        initial_value=room.get("solltemperatur"),
                        device_info=device_info,
                        room_data=room,
                    )
                )
    async_add_entities(sensors)


class ContromeRoomSensor(SensorEntity):
    """Representation of a sensor in a Controme room."""

    def __init__(self, base_url, house_id, floor_id, room_id, room_name, sensor_type, initial_value, device_info, room_data):
        """Initialize the sensor."""
        self._base_url = base_url
        self._house_id = house_id
        self._floor_id = floor_id
        self._room_id = room_id
        self._room_name = room_name
        self._sensor_type = sensor_type  # "current" oder "target"
        self._state = initial_value
        self._device_info = device_info
        self._room_data = room_data

        self._attr_unique_id = f"{DOMAIN}_{house_id}_{room_id}_{sensor_type}"
        if sensor_type == "current":
            self._attr_name = f"{room_name} Temperature"
        else:
            self._attr_name = f"{room_name} Target Temperature"
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def device_info(self):
        """Return device info for this sensor."""
        return self._device_info

    @property
    def extra_state_attributes(self):
        """Return the full room data as state attributes."""
        return self._room_data

    async def async_update(self):
        """Update sensor state from the API."""
        session = async_get_clientsession(self.hass)
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/temps/"
        try:
            async with session.get(endpoint) as response:
                if response.status != 200:
                    _LOGGER.error("Error updating sensors for house %s, status: %s", self._house_id, response.status)
                    return
                data = await response.json()
        except Exception as ex:
            _LOGGER.exception("Exception updating sensor data: %s", ex)
            return

        # Finde die Etage, die zu diesem Sensor gehört, und aktualisiere den entsprechenden Raumwert.
        for floor in data:
            if floor.get("id") == self._floor_id:
                rooms = floor.get("raeume", [])
                # Falls keine Räume unter "raeume" vorhanden sind, wird angenommen, dass der Floor selbst die Raumdaten enthält.
                if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
                    rooms = [floor]
                for room in rooms:
                    if room.get("id") == self._room_id:
                        # Update der kompletten Raumdaten.
                        self._room_data = room
                        if self._sensor_type == "current" and room.get("temperatur") is not None:
                            self._state = room.get("temperatur")
                        elif self._sensor_type == "target" and room.get("solltemperatur") is not None:
                            self._state = room.get("solltemperatur")
                        return
        _LOGGER.warning("Room %s not found during sensor update", self._room_id)