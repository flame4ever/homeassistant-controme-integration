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
- Operation mode status
- Transmission monitoring: shows when Controme last received sensor data and flags sensors that stopped transmitting
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

### Sensors
- Current Temperature
- Target Temperature
- Humidity
- Return Temperature (if available)
- Total Offset
- Operation Mode

### Transmission Monitoring (hub device)
The Controme hub device gets three diagnostic entities, based on the "last transmission" time Controme reports for every sensor:
- **Last transmission** (`sensor.controme_last_transmission`, timestamp): the newest transmission of all sensors
- **Stale sensors** (`sensor.controme_stale_sensors`, number): sensors whose last transmission is older than the threshold
- **Transmission problem** (`binary_sensor.controme_transmission_problem`, problem): on if at least one sensor is stale. The attributes `threshold_minutes` and `stale_sensors` list up to 20 stale sensors (oldest first) with room, description, name and last transmission.

The values are recalculated every minute, so a sensor keeps aging and the problem flag turns on even while the Controme system cannot be reached. Sensors without a readable timestamp never count as stale.

**Threshold:** Settings -> Devices & Services -> Controme -> Configure. A sensor is stale if it has not transmitted for longer than the threshold (5-1440 minutes, default 15). Controme reports times in whole minutes, so a sensor can be up to 59 seconds older than shown; the minimum of 5 minutes keeps the flag from flickering. Values below 5 that were stored by an earlier version are treated as 5.

**Time zone:** Controme reports local time without a time zone. The integration assumes the Home Assistant time zone, so it must be the same as the time zone of the Controme system, otherwise the times are off by the difference. In the repeated hour of the change from daylight saving time to standard time the timestamps are ambiguous; the first occurrence is used, so sensors can briefly appear one hour older. Times in the skipped hour of the change to daylight saving time (e.g. 02:30) are read as one hour later (03:30).

## Services

### `controme.set_temporary_temperature`
Sets a temporary target temperature for the selected Controme climate entities. Every selected entity is one request for exactly that room; there is no way to address all rooms at once.
- `temperature` (required): 5-30 °C in steps of 0.5
- `duration` (optional): approximate duration in minutes, 1-1440. Without a duration Controme uses its default duration.

Please note:
- The duration is only approximate. In a test the temporary value ended earlier than requested.
- Setting the temperature normally (`climate.set_temperature`) ends the temporary value.
- The Controme API reports no status of the temporary mode (no end time, no permanent target temperature). The new value is shown right away and confirmed by a refresh about 10 seconds later. The attributes `temporary_mode`, `temporary_until` and `permanent_target_temperature` only appear if a Controme firmware reports these documented fields.
- There is no service to cancel a temporary temperature; set the temperature normally instead.

```yaml
action: controme.set_temporary_temperature
target:
  entity_id: climate.controme_living_room
data:
  temperature: 21.5
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
- Controme scenes are not supported. In a test, Controme did not reliably apply a scene to a single room only, and a scene for all rooms is too risky.
- The duration of a temporary temperature is only approximate, and the API reports no status of the temporary mode. There is no separate service to cancel it; setting the temperature normally ends it.
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