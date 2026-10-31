# Controme Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release][releases-shield]][releases]
[![License][license-shield]](LICENSE)

![Integration Example](https://github.com/flame4ever/homeassistant-controme-integration/blob/main/Example.png)

Home Assistant integration for Controme heating systems. This integration allows you to control and monitor your Controme heating system through Home Assistant.

## Features

- Temperature control for each room
- Current temperature monitoring
- Humidity monitoring
- Return temperature sensors
- Total offset display
- Control deviation (current minus target temperature plus total offset)
- Valve position from the room outputs (disabled by default)
- Further humidity and temperature sensors of a room (disabled by default)
- Operation mode status
- Transmission monitoring: shows when Controme last received sensor data and flags sensors that stopped transmitting
- List of the Controme temperature scenes
- Services for temporary temperatures, resetting them and single-room scenes
- Automatic updates every 60 seconds

## Installation

### HACS (Recommended)
1. Add this repository to HACS as a custom repository
2. Install the "Controme" integration
3. Restart Home Assistant

### Manual Installation
1. Copy the `custom_components/controme` folder to your Home Assistant's `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to Settings -> Devices & Services
2. Click "Add Integration"
3. Search for "Controme"
4. Choose whether the integration should search your network for the Controme system or whether you enter it manually
5. Enter your Controme API details:
   - API URL (e.g., http://192.168.1.100/)
   - Username
   - Password

**Note on credentials:** During setup the integration only checks that the Controme system is reachable (the read API needs no login). Username and password are only checked when a target temperature is set. If they are wrong, setting a temperature fails with an authentication error.

## Removal

1. Go to Settings -> Devices & Services -> Controme, open the menu of the entry (three dots) and choose "Delete". This removes the devices and entities of the integration from Home Assistant.
2. If you installed via HACS: open HACS, select "Controme" and choose "Remove" (or "Uninstall"). With a manual installation, delete the folder `custom_components/controme` instead.
3. Restart Home Assistant.

Nothing is reset on the Controme system: target temperatures and temporary temperatures that were set via Home Assistant stay as they are. Change them in Controme if needed.

## Entities Created

For each room, the integration creates:

### Climate Entity
- Controls room temperature
- Shows current and target temperature
- Shows current humidity
- Shows the Controme operation mode as HVAC mode (heat, cool or off); it can only be changed in Controme
- Attribute `scenes`: the scenes that `controme.activate_scene` would accept for this room (`[{id, name}]`, only scenes that contain exactly this room; the default scene "*" never appears). The attribute is missing until the scene list was read once.

### Sensors
- Current Temperature
- Target Temperature
- Humidity
- Return Temperature (if available)
- Total Offset (unit °C as before, although it is a difference; changing the unit would break the long-term statistics)
- Operation Mode
- **Control Deviation** (`sensor.controme_<room>_control_deviation`, unit K): current temperature minus target temperature plus total offset, rounded to 0.01 K. Negative means too cold. Calculated from the room data without an extra request; only created for rooms with current and target temperature. A missing total offset counts as 0.
- **Valve Position** (`sensor.controme_<room>_valve`, %, disabled by default): mean of the room's outputs from `/outs/`. The attribute `outputs` lists the single outputs (e.g. `{"6": 0, "7": 25}`). Only created for rooms with outputs. On relay systems the outputs are only 0 or 1, so the value is 0-1 "%" there; that is why the sensor is disabled by default.
- **Further sensors** (`sensor.controme_<room>_sensor_<name>`, disabled by default): sensors of a room that are neither the room temperature sensor nor a return sensor, named after their Controme description, with the attributes `sensor_id` and `last_transmission`. Only sensors whose description clearly names humidity ("feuchte"/"humid", %) or temperature ("temp", °C) are created; all others are skipped (see the debug log), nothing is guessed.

### Transmission Monitoring (hub device)
The Controme hub device gets three diagnostic entities, based on the "last transmission" time Controme reports for every sensor:
- **Last transmission** (`sensor.controme_last_transmission`, timestamp): the newest transmission of all sensors
- **Stale sensors** (`sensor.controme_stale_sensors`, number): sensors whose last transmission is older than the threshold
- **Transmission problem** (`binary_sensor.controme_transmission_problem`, problem): on if at least one sensor is stale. The attributes `threshold_minutes` and `stale_sensors` list up to 20 stale sensors (oldest first) with room, description, name and last transmission.

The values are recalculated every minute, so a sensor keeps aging and the problem flag turns on even while the Controme system cannot be reached. Sensors without a readable timestamp never count as stale.

**Threshold:** Settings -> Devices & Services -> Controme -> Configure. A sensor is stale if it has not transmitted for longer than the threshold (5-1440 minutes, default 15). Controme reports times in whole minutes, so a sensor can be up to 59 seconds older than shown; the minimum of 5 minutes keeps the flag from flickering. Values below 5 that were stored by an earlier version are treated as 5.

**Time zone:** Controme reports local time without a time zone. The integration assumes the Home Assistant time zone, so it must be the same as the time zone of the Controme system, otherwise the times are off by the difference. In the repeated hour of the change from daylight saving time to standard time the timestamps are ambiguous; the first occurrence is used, so sensors can briefly appear one hour older. Times in the skipped hour of the change to daylight saving time (e.g. 02:30) are read as one hour later (03:30).

### Temperature Scenes (hub device)
- **Temperature scenes** (`sensor.controme_scenes`, diagnostic): number of scenes in Controme. The attribute `scenes` lists every scene with ID, name and the rooms it contains (`[{id, name, rooms}]`), e.g. to find the scene ID for `controme.activate_scene`. Every listed room belongs to the scene, whether the scene is currently active there or not.
- The scene list is read during setup, then at most every 10 minutes and after `controme.activate_scene`. If it cannot be read, the last list is kept.

### Hub Device Information
If the Controme system reports its software date, branch and hardware via `/info/`, they are shown as software and hardware version of the hub device. Many firmwares report nothing there; then the device stays as it is. CPU load, temperature and uptime of the Controme system are not available through the API.

## Services

### `controme.set_temporary_temperature`
Sets a temporary target temperature for the selected Controme climate entities. Every selected entity is one request for exactly that room; there is no way to address all rooms at once.
- `temperature` (required): 5-30 °C in steps of 0.5
- `duration` (optional): approximate duration in minutes, 1-1440. Without a duration Controme uses its default duration.

Please note:
- The duration is only approximate. In a test the temporary value ended earlier than requested.
- Setting the temperature normally (`climate.set_temperature`) ends the temporary value.
- The Controme API reports no status of the temporary mode (no end time, no permanent target temperature). The new value is shown right away and confirmed by a refresh about 10 seconds later. The attributes `temporary_mode`, `temporary_until` and `permanent_target_temperature` only appear if a Controme firmware reports these documented fields.
- To end a temporary temperature, use `controme.reset_temporary_temperature` (only with firmwares that report the permanent target temperature) or set the temperature normally.

```yaml
action: controme.set_temporary_temperature
target:
  entity_id: climate.controme_living_room
data:
  temperature: 21.5
  duration: 60
```

### `controme.reset_temporary_temperature`
Ends a temporary temperature of the selected Controme climate entities, one request per room. Controme has no reset call, but a normal target temperature ends the temporary value; so the service sends the permanent target temperature that Controme reports for the room (`perm_solltemperatur`) again. The permanent value itself does not change.
- No fields.
- If Controme does not report a permanent target temperature for the room, nothing is sent and an error is shown. The tested firmware does not report it, so there the service always shows this error; set the temperature normally instead.
- If Controme reports that the room has no temporary temperature, nothing is sent.

```yaml
action: controme.reset_temporary_temperature
target:
  entity_id: climate.controme_living_room
```

### `controme.activate_scene`
Activates a Controme temperature scene for the room of the selected climate entity. For safety, only scenes that contain **exactly this one room** are activated:
- `scene_id` (required): ID of the scene in Controme (1 or higher)
- `duration` (optional): approximate duration in minutes, 1-1440. Without a duration the scene stays active until the next switch.

How it works:
- Before anything is sent, the scene list of Controme is read. A scene contains all rooms it lists (rooms switched off in the scene in Controme are not listed); whether the scene is currently active in a room does not matter.
- The listed room is matched by its name "Floor / Room" (compared case-insensitively, also with umlauts). The scene is only sent if it lists exactly one room, this room is the room of the selected entity and its name is unique in Controme.
- Scenes for several rooms, for example the default scene "*", are refused on purpose, as are unknown scene IDs and other rooms. In these cases nothing is sent and a translated error is shown.
- The request always contains the room ID, but the live test showed that Controme applies a scene to all rooms it lists, regardless of the room ID. The protection of the other rooms therefore relies only on the check above. If Controme reports that the scene was applied to other rooms as well, an error with these room names is shown and a warning is logged.
- To use a scene for one room, create a scene in Controme that contains only this room. Selecting several climate entities means one check and one request per room.
- The attribute `scenes` of a climate entity lists the scenes this check accepts for the room; `sensor.controme_scenes` lists all scenes.

```yaml
action: controme.activate_scene
target:
  entity_id: climate.controme_living_room
data:
  scene_id: 2
  duration: 60
```

## Supported Languages
- English
- German (Deutsch)

## Requirements
- Home Assistant 2026.8.0 or newer
- Controme heating system with API access

## Known Limitations
- Several Controme systems with the same haus_id are not supported. The IDs of devices and entities are built from haus_id, floor and room, so a second system with the same haus_id would collide with the first one. The haus_id (usually 1, sometimes 2) is entered during setup.
- The HVAC mode (Controme operation mode) cannot be switched from Home Assistant. The firmware tested rejects the documented API call for it (HTTP 400).
- Controme scenes can only be activated if they contain exactly one room (see `controme.activate_scene`). Scenes for several rooms or all rooms are refused, there are no scene entities.
- The duration of a temporary temperature is only approximate, and the API reports no status of the temporary mode. `controme.reset_temporary_temperature` only works with firmwares that report the permanent target temperature; setting the temperature normally always ends it.
- Heating programs (schedules) cannot be switched or shown: the API has no call for it. Scenes are the alternative.
- CPU load, temperature and uptime of the Controme system are not available through the API. Software and hardware version are only shown if the firmware reports them.
- The valve position cannot tell relay outputs (0/1) from valve positions (0-100); the meaning depends on the Controme hardware. Outputs are read only, they cannot be set.
- Further room sensors are only created if their description clearly names humidity or temperature. Other sensor types (e.g. of a room controller or a wireless thermometer) are not created.
- The total offset keeps the unit °C (with the temperature device class) for compatibility; for Fahrenheit users the converted value of this difference is not meaningful. The control deviation uses K without device class and is not converted.
- Floors without rooms and rooms without their own ID are shown, but neither a target temperature nor a temporary temperature can be set for them.
- The transmission monitoring entities use the haus_id in their IDs as well (e.g. `1_transmission_problem`), so they are affected by the same haus_id limitation.

## Support

If you have any issues or feature requests, please:
1. Check the [Issues](https://github.com/flame4ever/homeassistant-controme-integration/issues) page
2. Create a new issue if your problem isn't already listed

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

[releases-shield]: https://img.shields.io/github/release/flame4ever/homeassistant-controme-integration.svg
[releases]: https://github.com/flame4ever/homeassistant-controme-integration/releases
[license-shield]: https://img.shields.io/github/license/flame4ever/homeassistant-controme-integration.svg