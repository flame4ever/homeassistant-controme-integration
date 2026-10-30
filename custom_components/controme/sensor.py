"""Support for Controme sensors."""
import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
    SensorEntityDescription,
)
from homeassistant.const import (
    UnitOfTemperature,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .coordinator import ContromeConfigEntry
from .helpers import find_room, iter_rooms, to_float
from .const import (
    DOMAIN,
    CONF_HAUS_ID,
    ENTITY_ID_MAP,
    VALUE_MAP,
    SENSOR_TYPE_OPERATION_MODE,
)

from dataclasses import dataclass

_LOGGER = logging.getLogger(__name__)
# Sensors only read coordinator data, so updates need no limit
PARALLEL_UPDATES = 0

@dataclass(frozen=True, kw_only=True)
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

async def async_setup_entry(hass: HomeAssistant, entry: ContromeConfigEntry, async_add_entities):
    """Set up the Controme sensor platform."""
    sensors = []
    coordinator = entry.runtime_data
    data = coordinator.data
    house_id = entry.data[CONF_HAUS_ID]

    if not data:
        _LOGGER.error("No data received from coordinator")
        return

    # Process all floors and rooms
    for floor_id, room_id, room in iter_rooms(data):
        room_name = room.get("name") or f"Room {room_id}"
        _LOGGER.debug("Processing room %s", room_name)

        # Add room data
        room["floor_id"] = floor_id
        room["room_id"] = room_id
        device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{house_id}_{floor_id}_{room_id}")},
            name=room_name,
            manufacturer="Controme",
            model="Room",
            via_device_id=coordinator.hub_device_id,
        )

        # Add basic sensors
        for sensor_type, data_key in VALUE_MAP.items():
            _LOGGER.debug("Checking for %s sensor (key: %s) in room data: %s", 
                        sensor_type, data_key, data_key in room)
            if data_key in room:
                _LOGGER.debug("Adding %s sensor for room %s", sensor_type, room_name)
                if sensor_type == SENSOR_TYPE_OPERATION_MODE:
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
        base_type = "return" if sensor_type.startswith("return_") else sensor_type
        self.entity_description = next(
            (desc for desc in SENSOR_TYPES if desc.key == base_type),
            SENSOR_TYPES[0]  # Fallback to temperature sensor
        )

    def __init_entity_id(self, sensor_type: str, room_name: str) -> None:
        """Initialize the entity ID."""
        room_name_lower = slugify(room_name)
        suffix = "return" if sensor_type.startswith("return_") else ENTITY_ID_MAP.get(sensor_type, sensor_type)
        self.entity_id = f"sensor.controme_{room_name_lower}_{suffix}"

    def __init__(self, coordinator, config_entry, room_data, sensor_type, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        _LOGGER.debug("Initializing sensor with type %s for room %s", 
                    sensor_type, room_data.get("name"))
        
        # Set basic attributes
        self._device_info = device_info
        self._sensor_type = sensor_type
        self._room_id = room_data.get("room_id", room_data.get("id"))
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        
        # Set unique ID and entity ID
        self._attr_unique_id = f"{self._house_id}_{self._floor_id}_{self._room_id}_{sensor_type}"
        self.__init_sensor_description(sensor_type)
        self.__init_entity_id(sensor_type, room_data.get("name") or f"room_{self._room_id}")
        # The name comes from the translation_key, return sensors use their Controme description
        if sensor_type.startswith("return_"):
            sensor_name = sensor_type[len("return_"):]
            description = next(
                (sensor.get("beschreibung") for sensor in room_data.get("sensoren", [])
                 if sensor.get("name") == sensor_name),
                None,
            )
            self._attr_translation_placeholders = {"sensor": description or sensor_name}
        
        # Set initial values
        self._update_from_data(room_data)

    @property
    def device_info(self):
        """Return device info for this sensor."""
        return self._device_info

    @property
    def available(self) -> bool:
        """Return if the coordinator is up and the sensor has a valid value."""
        # CoordinatorEntity.available only reflects the last coordinator update
        return super().available and self._has_value

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
        room = find_room(self.coordinator.data, self._floor_id, self._room_id)
        if room is None:
            self._has_value = False
        else:
            self._update_from_data(room)
        self.async_write_ha_state()

    def _update_from_data(self, room_data):
        """Update sensor state from room data."""
        if self._sensor_type.startswith("return_"):
            for sensor in room_data.get("sensoren", []):
                sensor_id = "_".join(self._sensor_type.split("_")[1:])
                if sensor.get("name") == sensor_id:
                    value = to_float(sensor.get("wert"))
                    # Non-numeric values like "kein Sensor vorhanden" mark the sensor unavailable
                    self._attr_native_value = value
                    self._has_value = value is not None
                    break
            else:
                # The return sensor is no longer reported for this room
                self._has_value = False
        else:
            value = room_data.get(VALUE_MAP.get(self._sensor_type))
            # For numeric sensors, ensure we have numeric values
            if self.entity_description.device_class in [
                SensorDeviceClass.TEMPERATURE, 
                SensorDeviceClass.HUMIDITY
            ]:
                # 0 and negative values (e.g. offsets) are valid readings
                value = to_float(value)
                self._attr_native_value = value
                self._has_value = value is not None
            else:
                self._attr_native_value = value
                self._has_value = value is not None

class ContromeOperationModeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Controme Operation Mode Sensor."""

    _attr_has_entity_name = True

    def __init__(self, coordinator, config_entry, room_data, sensor_type, device_info):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._device_info = device_info
        self._room_id = room_data.get("room_id", room_data.get("id"))
        self._floor_id = room_data.get("floor_id")
        self._house_id = config_entry.data[CONF_HAUS_ID]
        
        # Set unique ID and entity ID
        self._attr_unique_id = f"{self._house_id}_{self._floor_id}_{self._room_id}_operation_mode"
        room_name = room_data.get("name") or f"room_{self._room_id}"
        room_name_lower = slugify(room_name)
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

        # Set initial value and availability
        self._update_from_data(room_data)

    @property
    def device_info(self):
        """Return device info for this sensor."""
        return self._device_info

    @property
    def available(self) -> bool:
        """Return if the coordinator is up and the sensor has a valid value."""
        # CoordinatorEntity.available only reflects the last coordinator update
        return super().available and self._has_value

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        room = find_room(self.coordinator.data, self._floor_id, self._room_id)
        if room is None:
            self._has_value = False
        else:
            self._update_from_data(room)
        self.async_write_ha_state()
        
    def _update_from_data(self, room_data):
        """Update the sensor state from room data."""
        value = room_data.get(VALUE_MAP["operation_mode"])
        self._attr_native_value = value
        self._has_value = value is not None