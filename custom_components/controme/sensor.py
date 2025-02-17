"""Support for Controme sensors."""
import logging
from typing import Any
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, CONF_API_URL, CONF_HAUS_ID, KEY_TEMPERATURE, KEY_TARGET_TEMPERATURE, KEY_HUMIDITY, KEY_TOTAL_OFFSET, KEY_OPERATION_MODE, KEY_RETURN

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the Controme sensor platform."""
    sensors = []
    base_url = entry.data.get(CONF_API_URL)
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

    # Process all floors and rooms
    for floor in data:
        floor_id = floor.get("id")
        floor_name = floor.get("etagenname", f"Floor {floor_id}")
        rooms = floor.get("raeume", [])
        
        if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
            rooms = [floor]
            
        for room in rooms:
            room_id = room.get("id")
            if not room_id:
                room_id = f"{floor_id}_{index}"
            room_name = room.get("name", f"Room {room_id}")

            # Base device info for the room
            device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{house_id}_{floor_id}_{room_id}")},
                name=room_name,
                manufacturer="Controme",
                model="Thermostat API",
                via_device=(DOMAIN, f"{house_id}"),
            )

            # Create sensors for each available value
            if "temperatur" in room:
                sensors.append(
                    ContromeSensor(
                        base_url,
                        house_id,
                        floor_id,
                        room_id,
                        room_name,
                        "current",
                        device_info,
                        room,
                    )
                )

            if "solltemperatur" in room:
                sensors.append(
                    ContromeSensor(
                        base_url,
                        house_id,
                        floor_id,
                        room_id,
                        room_name,
                        "target",
                        device_info,
                        room,
                    )
                )

            if "luftfeuchte" in room:
                sensors.append(
                    ContromeSensor(
                        base_url,
                        house_id,
                        floor_id,
                        room_id,
                        room_name,
                        "humidity",
                        device_info,
                        room,
                    )
                )

            # Add sensors for all return temperatures
            for sensor in room.get("sensoren", []):
                if "Rücklauf" in sensor.get("beschreibung", ""):
                    sensor_id = sensor.get("name")
                    sensors.append(
                        ContromeSensor(
                            base_url,
                            house_id,
                            floor_id,
                            room_id,
                            room_name,
                            f"return_{sensor_id}",
                            device_info,
                            room,
                            sensor.get("beschreibung"),
                        )
                    )

            # Add total offset
            if "total_offset" in room:
                sensors.append(
                    ContromeSensor(
                        base_url,
                        house_id,
                        floor_id,
                        room_id,
                        room_name,
                        "total_offset",
                        device_info,
                        room,
                    )
                )

            # Add operation mode
            if "betriebsart" in room:
                sensors.append(
                    ContromeSensor(
                        base_url,
                        house_id,
                        floor_id,
                        room_id,
                        room_name,
                        "operation_mode",
                        device_info,
                        room,
                    )
                )

    async_add_entities(sensors)

class ContromeSensor(SensorEntity):
    """Representation of a Controme Sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        base_url: str,
        house_id: str,
        floor_id: str,
        room_id: str,
        room_name: str,
        sensor_type: str,
        device_info: DeviceInfo,
        room_data: dict,
        description: str = None,
    ):
        """Initialize the sensor."""
        self._base_url = base_url
        self._house_id = house_id
        self._floor_id = floor_id
        self._room_id = room_id
        self._sensor_type = sensor_type
        self._device_info = device_info
        self._room_data = room_data
        self._attr_unique_id = f"{house_id}_{floor_id}_{room_id}_{sensor_type}"
        room_name_lower = room_name.lower()
        
        # Set names and attributes based on sensor type
        if sensor_type == "current":
            self._attr_name = "Temperature"
            self.entity_id = f"sensor.controme_{room_name_lower}_temperature"
            self._attr_translation_key = "current"
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_value = room_data.get("temperatur")
        elif sensor_type == "target":
            self._attr_name = "Target"
            self.entity_id = f"sensor.controme_{room_name_lower}_target"
            self._attr_translation_key = "target"
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_value = room_data.get("solltemperatur")
        elif sensor_type == "humidity":
            self._attr_name = "Humidity"
            self.entity_id = f"sensor.controme_{room_name_lower}_humidity"
            self._attr_translation_key = "humidity"
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_device_class = SensorDeviceClass.HUMIDITY
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_value = room_data.get("luftfeuchte")
        elif sensor_type.startswith("return_"):
            room_description = description.split(" ")[-1] if description else ""
            self._attr_name = "Return"
            self.entity_id = f"sensor.controme_{room_name_lower}_return"
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            # Find the corresponding sensor in sensor data
            for sensor in room_data.get("sensoren", []):
                if sensor.get("name") in sensor_type:
                    self._attr_native_value = sensor.get("wert")
                    break
        elif sensor_type == "total_offset":
            self._attr_name = "Offset"
            self.entity_id = f"sensor.controme_{room_name_lower}_offset"
            self._attr_translation_key = "total_offset"
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_state_class = SensorStateClass.MEASUREMENT
            self._attr_native_value = room_data.get("total_offset")
        elif sensor_type == "operation_mode":
            self._attr_name = "Mode"
            self.entity_id = f"sensor.controme_{room_name_lower}_mode"
            self._attr_translation_key = "operation_mode"
            self._attr_native_value = room_data.get("betriebsart")

    @property
    def device_info(self):
        """Return device info for this sensor."""
        return self._device_info

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "room_id": self._room_id,
            "floor_id": self._floor_id,
            "house_id": self._house_id,
        }

    async def async_update(self):
        """Update sensor state."""
        session = async_get_clientsession(self.hass)
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/temps/"
        try:
            async with session.get(endpoint) as response:
                if response.status != 200:
                    _LOGGER.error("Error updating sensors for house %s, status: %s", 
                                self._house_id, response.status)
                    return
                data = await response.json()
        except Exception as ex:
            _LOGGER.exception("Exception updating sensor data: %s", ex)
            return

        # Find the corresponding room and update values
        for floor in data:
            if floor.get("id") == self._floor_id:
                rooms = floor.get("raeume", [])
                if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
                    rooms = [floor]
                for room in rooms:
                    if room.get("id") == self._room_id:
                        self._room_data = room
                        if self._sensor_type == "current":
                            self._attr_native_value = room.get("temperatur")
                        elif self._sensor_type == "target":
                            self._attr_native_value = room.get("solltemperatur")
                        elif self._sensor_type == "humidity":
                            self._attr_native_value = room.get("luftfeuchte")
                        elif self._sensor_type.startswith("return_"):
                            for sensor in room.get("sensoren", []):
                                if sensor.get("name") in self._sensor_type:
                                    self._attr_native_value = sensor.get("wert")
                                    break
                        elif self._sensor_type == "total_offset":
                            self._attr_native_value = room.get("total_offset")
                        elif self._sensor_type == "operation_mode":
                            self._attr_native_value = room.get("betriebsart")
                        return