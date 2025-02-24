"""Support for Controme sensors."""
import logging
from typing import Any
from datetime import timedelta

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from aiohttp import ClientTimeout
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, CoordinatorEntity
from homeassistant.helpers import device_registry as dr

from .const import (
    DOMAIN, 
    CONF_API_URL, 
    CONF_HAUS_ID,
    ENTITY_ID_MAP,
    VALUE_MAP,
    SENSOR_TYPE_OPERATION_MODE,
)

from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=60)
REQUEST_TIMEOUT = ClientTimeout(total=10)  # 10 Sekunden Timeout

@dataclass
class ContromeSensorEntityDescription(SensorEntityDescription):
    """Describes Controme sensor entity."""

SENSOR_TYPES: tuple[ContromeSensorEntityDescription, ...] = (
    ContromeSensorEntityDescription(
        key="current",
        translation_key="current",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ContromeSensorEntityDescription(
        key="target",
        translation_key="target",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ContromeSensorEntityDescription(
        key="return",
        translation_key="return",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ContromeSensorEntityDescription(
        key="total_offset",
        translation_key="total_offset",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    ),
    ContromeSensorEntityDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
    ),
)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up the Controme sensor platform."""
    sensors = []
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    data = coordinator.data
    house_id = entry.data[CONF_HAUS_ID]

    # Create hub device
    hub_device_info = DeviceInfo(
        identifiers={(DOMAIN, house_id)},
        name="Controme Hub",
        manufacturer="Controme",
        model="Hub",
    )

    _LOGGER.debug("Setting up Controme sensors with data: %s", data)

    if not data:
        _LOGGER.error("No data received from coordinator")
        return

    # Process all floors and rooms
    for floor in data:
        floor_id = floor.get("id")
        floor_name = floor.get("etagenname", f"Floor {floor_id}")
        rooms = floor.get("raeume", [])
        _LOGGER.debug("Processing floor %s with rooms: %s", floor_id, rooms)
        
        if not rooms and ("temperatur" in floor or "solltemperatur" in floor):
            rooms = [floor]
            _LOGGER.debug("Using floor as room because no rooms found")
            
        for room in rooms:
            room_id = room.get("id")
            if not room_id:
                room_id = f"{floor_id}_{index}"
            room_name = room.get("name", f"Room {room_id}")
            _LOGGER.debug("Processing room %s with data: %s", room_name, room)

            # Add room data
            room["floor_id"] = floor_id
            device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{house_id}_{floor_id}_{room_id}")},
                name=room_name,
                manufacturer="Controme",
                model="Room",
                via_device=(DOMAIN, house_id),
            )

            # Add basic sensors
            for sensor_type, data_key in VALUE_MAP.items():
                _LOGGER.debug("Checking for %s sensor (key: %s) in room data: %s", 
                            sensor_type, data_key, data_key in room)
                if data_key in room:
                    _LOGGER.debug("Adding %s sensor for room %s", sensor_type, room_name)
                    if sensor_type == "operation_mode":
                        sensor_class = ContromeOperationModeSensor
                    else:
                        sensor_class = ContromeSensor
                    sensors.append(
                        sensor_class(
                            coordinator,
                            entry,
                            room,
                            sensor_type,
                            device_info,
                        )
                    )
                    _LOGGER.debug("%s sensor added", sensor_type)

            # Process return temperature sensors
            for sensor in room.get("sensoren", []):
                if "Rücklauf" in sensor.get("beschreibung", ""):
                    _LOGGER.debug("Adding return sensor %s for room %s", 
                                sensor.get("name"), room_name)
                    sensors.append(
                        ContromeSensor(
                            coordinator,
                            entry,
                            room,
                            f"return_{sensor.get('name')}",
                            device_info,
                        )
                    )
                    _LOGGER.debug("Return sensor added")

    _LOGGER.debug("Created %d sensors in total", len(sensors))
    async_add_entities(sensors)

class ContromeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Controme Sensor."""

    _attr_has_entity_name = True

    def __init_sensor_description(self, sensor_type: str) -> None:
        """Initialize the sensor description based on type."""
        base_type = sensor_type.split("_")[0]
        self.entity_description = next(
            (desc for desc in SENSOR_TYPES if desc.key == base_type),
            SENSOR_TYPES[0]  # Fallback to temperature sensor
        )

    def __init_entity_id(self, sensor_type: str, room_name: str) -> None:
        """Initialize the entity ID."""
        room_name_lower = room_name.lower().replace(" ", "_")
        suffix = "return" if sensor_type.startswith("return_") else ENTITY_ID_MAP.get(sensor_type, sensor_type)
        self.entity_id = f"sensor.controme_{room_name_lower}_{suffix}"

    def __init_name(self, sensor_type: str) -> None:
        """Initialize the sensor name."""
        name_map = {
            "current": "Temperatur",
            "target": "Zieltemperatur",
            "humidity": "Luftfeuchtigkeit",
            "return": "Rücklauftemperatur",
            "total_offset": "Temperaturanpassung",
            "operation_mode": "Betriebsart"
        }
        base_type = sensor_type.split("_")[0]
        lookup_key = sensor_type if sensor_type == "total_offset" else base_type
        self._attr_name = name_map.get(lookup_key, sensor_type)

    def __init__(self, coordinator, config_entry, room_data, sensor_type, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        _LOGGER.debug("Initializing sensor with type %s for room %s", 
                    sensor_type, room_data.get("name"))
        
        # Set basic attributes
        self._config_entry = config_entry
        self._device_info = device_info
        self._room_data = room_data
        self._sensor_type = sensor_type
        self._room_id = room_data.get("id")
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        self._base_url = config_entry.data[CONF_API_URL].rstrip('/')
        
        # Set unique ID and entity ID
        self._attr_unique_id = f"{self._house_id}_{self._floor_id}_{self._room_id}_{sensor_type}"
        self.__init_sensor_description(sensor_type)
        self.__init_entity_id(sensor_type, room_data.get("name", ""))
        self.__init_name(sensor_type)
        
        # Set initial values
        self._update_from_data(room_data)

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

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        for floor in self.coordinator.data:
            if floor["id"] == self._floor_id:
                for room in floor.get("raeume", []):
                    if room["id"] == self._room_id:
                        self._update_from_data(room)
                        break
        self.async_write_ha_state()

    async def async_update(self):
        """Update sensor state."""
        session = async_get_clientsession(self.hass)
        endpoint = f"{self._base_url}/get/json/v1/{self._house_id}/temps/"
        try:
            async with session.get(endpoint, timeout=REQUEST_TIMEOUT) as response:
                if response.status != 200:
                    _LOGGER.error("Error updating sensors for house %s, status: %s", 
                                self._house_id, response.status)
                    return
                data = await response.json()
        except Exception as ex:
            _LOGGER.warning("Error updating sensor data: %s - Will retry next update", str(ex))
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
                        self._update_from_data(room)
                        return

    def _update_from_data(self, room_data):
        """Update sensor state from room data."""
        if self._sensor_type.startswith("return_"):
            for sensor in room_data.get("sensoren", []):
                sensor_id = "_".join(self._sensor_type.split("_")[1:])
                if sensor.get("name") == sensor_id:
                    self._attr_native_value = sensor.get("wert")
                    break
        else:
            self._attr_native_value = room_data.get(VALUE_MAP.get(self._sensor_type))

class ContromeOperationModeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Controme Operation Mode Sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, config_entry, room_data, sensor_type, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._device_info = device_info
        self._room_data = room_data
        self._room_id = room_data.get("id")
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        
        # Set unique ID and entity ID
        self._attr_unique_id = f"{self._house_id}_{self._floor_id}_{self._room_id}_operation_mode"
        room_name = room_data.get("name", "")
        room_name_lower = room_name.lower().replace(" ", "_")
        self.entity_id = f"sensor.controme_{room_name_lower}_mode"

        # Set entity description
        self.entity_description = ContromeSensorEntityDescription(
            key="operation_mode",
            translation_key="operation_mode",
            device_class=None,
            state_class=None,
            native_unit_of_measurement=None,
            has_entity_name=True,
        )

        # Set name
        self._attr_name = "Betriebsart"

        # Set initial value
        self._attr_native_value = room_data.get(VALUE_MAP["operation_mode"])

    @property
    def device_info(self):
        """Return device info for this sensor."""
        return self._device_info

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        for floor in self.coordinator.data:
            if floor["id"] == self._floor_id:
                for room in floor.get("raeume", []):
                    if room["id"] == self._room_id:
                        self._attr_native_value = room.get(VALUE_MAP["operation_mode"])
                        break
        self.async_write_ha_state()