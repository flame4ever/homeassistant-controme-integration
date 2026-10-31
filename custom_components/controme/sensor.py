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
from .entity import ContromeTransmissionEntity
from .helpers import (
    ROOM_SENSOR_KIND_HUMIDITY,
    ROOM_SENSOR_KIND_TEMPERATURE,
    classify_room_sensor,
    control_deviation,
    find_room,
    is_return_sensor,
    iter_rooms,
    normalize_outputs,
    parse_transmission,
    to_float,
    valve_position,
)
from .const import (
    DOMAIN,
    CONF_HAUS_ID,
    ENTITY_ID_MAP,
    VALUE_MAP,
    SENSOR_TYPE_OPERATION_MODE,
    SENSOR_TYPE_CONTROL_DEVIATION,
    SENSOR_TYPE_VALVE,
    SENSOR_TYPE_ROOM_SENSOR_PREFIX,
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
    # A temperature difference: without a device class HA does not convert it like
    # an absolute temperature (a difference of 1 K is 1.8 °F, not 33.8 °F)
    ContromeSensorEntityDescription(
        key=SENSOR_TYPE_CONTROL_DEVIATION,
        translation_key=SENSOR_TYPE_CONTROL_DEVIATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="K",
        suggested_display_precision=2,
    ),
    # Disabled by default: relay systems report 0/1, which would show as 0 or 1 %
    ContromeSensorEntityDescription(
        key=SENSOR_TYPE_VALVE,
        translation_key=SENSOR_TYPE_VALVE,
        icon="mdi:valve",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
    ),
    # Further room sensors (e.g. "LuftFeuchte Bad"), disabled by default as they
    # often duplicate the room values; the name is the Controme description
    ContromeSensorEntityDescription(
        key=f"room_sensor_{ROOM_SENSOR_KIND_TEMPERATURE}",
        translation_key="room_sensor",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_registry_enabled_default=False,
    ),
    ContromeSensorEntityDescription(
        key=f"room_sensor_{ROOM_SENSOR_KIND_HUMIDITY}",
        translation_key="room_sensor",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_enabled_default=False,
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

        # Control deviation, calculated from the room data without an extra request
        if "temperatur" in room and "solltemperatur" in room:
            sensors.append(
                ContromeSensor(coordinator, entry, room, SENSOR_TYPE_CONTROL_DEVIATION, device_info)
            )

        # Valve position, only for rooms with outputs in /outs/
        ausgang = room.get("ausgang")
        if isinstance(ausgang, dict) and ausgang:
            sensors.append(ContromeSensor(coordinator, entry, room, SENSOR_TYPE_VALVE, device_info))

        # Process return temperature sensors
        for sensor in room.get("sensoren", []):
            if is_return_sensor(sensor.get("beschreibung")):
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

        # Further sensors of the room, only if clearly humidity or temperature
        seen_names = set()
        for sensor in room.get("sensoren") or []:
            if not isinstance(sensor, dict) or sensor.get("raumtemperatursensor") is True:
                continue
            if is_return_sensor(sensor.get("beschreibung")):
                continue
            name = sensor.get("name")
            if classify_room_sensor(sensor) is None or name in seen_names:
                _LOGGER.debug("Skipping sensor %s (%s) of room %s: not clearly humidity or "
                              "temperature, or reported twice", name, sensor.get("beschreibung"),
                              room_name)
                continue
            seen_names.add(name)
            sensors.append(
                ContromeSensor(
                    coordinator, entry, room, f"{SENSOR_TYPE_ROOM_SENSOR_PREFIX}{name}", device_info
                )
            )

    # Transmission monitoring on the hub device
    sensors.append(ContromeLastTransmissionSensor(coordinator, entry))
    sensors.append(ContromeStaleSensorsSensor(coordinator, entry))

    _LOGGER.debug("Created %d sensors in total", len(sensors))
    async_add_entities(sensors)

class ContromeSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Controme Sensor."""

    _attr_has_entity_name = True

    def __init_sensor_description(self, sensor_type: str, room_data) -> None:
        """Initialize the sensor description based on type."""
        base_type = "return" if sensor_type.startswith("return_") else sensor_type
        if sensor_type.startswith(SENSOR_TYPE_ROOM_SENSOR_PREFIX):
            # The kind is fixed at creation, so the unit never changes later
            base_type = f"room_sensor_{classify_room_sensor(self._find_sensor(room_data))}"
        self.entity_description = next(
            (desc for desc in SENSOR_TYPES if desc.key == base_type),
            SENSOR_TYPES[0]  # Fallback to temperature sensor
        )

    def __init_entity_id(self, sensor_type: str, room_name: str) -> None:
        """Initialize the entity ID."""
        room_name_lower = slugify(room_name)
        suffix = "return" if sensor_type.startswith("return_") else ENTITY_ID_MAP.get(sensor_type, sensor_type)
        if sensor_type.startswith(SENSOR_TYPE_ROOM_SENSOR_PREFIX):
            sensor_name = sensor_type[len(SENSOR_TYPE_ROOM_SENSOR_PREFIX):]
            suffix = f"{SENSOR_TYPE_ROOM_SENSOR_PREFIX}{slugify(sensor_name)}"
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
        self.__init_sensor_description(sensor_type, room_data)
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
        elif sensor_type.startswith(SENSOR_TYPE_ROOM_SENSOR_PREFIX):
            sensor = self._find_sensor(room_data) or {}
            self._attr_translation_placeholders = {
                "sensor": sensor.get("beschreibung") or self._room_sensor_name
            }
        self._last_transmission = None

        # Set initial values
        self._update_from_data(room_data)

    @property
    def _room_sensor_name(self) -> str:
        """Return the Controme sensor name of a further room sensor ("sensor_{name}")."""
        return self._sensor_type[len(SENSOR_TYPE_ROOM_SENSOR_PREFIX):]

    def _find_sensor(self, room_data):
        """Return the entry of "sensoren" of a further room sensor, or None if it is gone."""
        return next(
            (sensor for sensor in room_data.get("sensoren") or []
             if isinstance(sensor, dict) and sensor.get("name") == self._room_sensor_name),
            None,
        )

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
        attributes = {
            "room_id": self._room_id,
            "floor_id": self._floor_id,
            "house_id": self._house_id,
        }
        if self._sensor_type == SENSOR_TYPE_VALVE:
            attributes["outputs"] = self._outputs
        elif self._sensor_type.startswith(SENSOR_TYPE_ROOM_SENSOR_PREFIX):
            attributes["sensor_id"] = self._room_sensor_name
            attributes["last_transmission"] = self._last_transmission
        return attributes

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
        elif self._sensor_type.startswith(SENSOR_TYPE_ROOM_SENSOR_PREFIX):
            sensor = self._find_sensor(room_data)
            if sensor is None:
                # The sensor is no longer reported for this room
                self._has_value = False
                return
            value = to_float(sensor.get("wert"))
            timestamp = parse_transmission(sensor.get("letzte_uebertragung"))
            self._last_transmission = timestamp.isoformat() if timestamp else None
            self._attr_native_value = value
            self._has_value = value is not None
        elif self._sensor_type == SENSOR_TYPE_CONTROL_DEVIATION:
            value = control_deviation(room_data)
            self._attr_native_value = value
            self._has_value = value is not None
        elif self._sensor_type == SENSOR_TYPE_VALVE:
            # Without /outs/ data (request failed) the sensor is unavailable
            self._outputs = normalize_outputs(room_data.get("ausgang"))
            value = valve_position(self._outputs)
            self._attr_native_value = value
            self._has_value = value is not None
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

class ContromeLastTransmissionSensor(ContromeTransmissionEntity, SensorEntity):
    """Newest last transmission of all Controme sensors."""

    _platform_domain = "sensor"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, config_entry):
        """Initialize the sensor on the hub device."""
        super().__init__(coordinator, config_entry, "last_transmission")

    @property
    def native_value(self):
        """Return the newest transmission (timezone aware), or None if unknown."""
        return self._newest

class ContromeStaleSensorsSensor(ContromeTransmissionEntity, SensorEntity):
    """Number of Controme sensors whose last transmission is older than the threshold."""

    _platform_domain = "sensor"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, config_entry):
        """Initialize the sensor on the hub device."""
        super().__init__(coordinator, config_entry, "stale_sensors")

    @property
    def native_value(self):
        """Return the number of stale sensors."""
        return self._stale_count