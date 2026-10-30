# Changelog

## 2.0.0 (2026-10-30)

> **Breaking:** Home Assistant 2026.8.0 or newer is required. Entity IDs and unique IDs stay the same, but some display names change and climate entities now show the Controme operation mode and heating activity.

### Bug Fixes
- **Offset Sensors**: Values of 0 and negative values (e.g. total offset) no longer mark the sensor as unavailable
- **Entity IDs**: Room names with umlauts or special characters (e.g. "Küche", "WC & Flur") now produce valid entity IDs (#25)
- **Rooms Without ID**: Fixed a crash during setup when a room has no ID
- **Floor as Room**: Entities created from floors without rooms now receive updates
- **Removed Rooms**: Entities become unavailable when their room disappears from the API data
- **Climate HVAC Mode**: The HVAC mode follows the Controme operation mode (heating, cooling, off) instead of always showing "Heat"; the non-functional "Off" option is gone (#10, #22). Integer values (also as digit strings) are mapped as 0 = off, 1 = cooling, 2 = heating; this mapping comes from issue #22 and is not documented by Controme. Boolean and unknown values fall back to heating.
- **Climate HVAC Action**: Climate entities show whether a room is actively heating or idle, based on the room's outputs from `/outs/` (#10). Malformed `/outs/` data is skipped and never makes the update fail. `/outs/` has its own 5 second timeout, the main update keeps 10 seconds.
- **Return Sensors Not Found**: Return sensors described as "... RL" or "Return ..." are detected, not only "Rücklauf" (#5, #13)
- **Haus ID**: The house ID can be entered during setup (default 1) instead of being hard coded (#9). Only digits are accepted, leading zeros are removed ("01" is stored as "1"), and the duplicate check compares the normalized IDs. Existing entries are not migrated.
- **Renaming Entities**: Renaming an entity, assigning an area or enabling/disabling it no longer leaves it without a state (#23)
- **Set Temperature Errors**: Failures (wrong credentials, connection errors) are now shown in the UI, and the request has a timeout
- **Return Sensors**: Return temperatures are reported as numbers
- **Config Flow**: The same Controme system can no longer be added twice; the connection test uses Home Assistant's HTTP session and no longer sends misleading Basic Auth
- **Availability**: Entities now really become unavailable when their room disappears or a value is missing or not numeric. Before, the coordinator entity ignored this and only reflected the last update.
- **Config Flow Errors**: Errors are shown on the step where they occurred (credentials, system selection, manual entry) instead of the system selection step
- **Set Temperature on Floors**: Floors without rooms and rooms without their own ID now reject setting a temperature with a clear error instead of sending it to a wrong room ID
- **Coordinator**: Responses without JSON content type are parsed; connection errors are reported once by the coordinator instead of being logged twice

### Changes
- **Entity Names**: Sensor names now come from the translations instead of hard coded German texts. English installations show English names. Return temperature sensors include their sensor name, so several return sensors in one room can be told apart. Climate entities take the name of their room device. Entity IDs and unique IDs are unchanged.
- **Config Flow**: All steps (user, manual entry, credentials, system selection) and the discovery method options are translated in English and German. The descriptions point out that credentials are only checked when a temperature is set.
- **Return Sensors**: Return temperature sensors are named after their Controme description (e.g. "Rücklauf 1 Wohnraum") instead of the hardware ID
- **Device Model**: Room devices consistently use the model "Room"
- **Operation Mode**: Removed state translations that never matched the values reported by Controme ("Heating")
- **Requirements**: Home Assistant 2026.8.0 or newer is required (via_device_id for devices)
- **Documentation**: README lists the limitation that several Controme systems with the same haus_id are not supported

### Under the Hood
- Coordinator stored in `entry.runtime_data` instead of `hass.data`; config entry passed to the coordinator
- Room devices link to the hub device via `via_device_id` (the `via_device` tuple is deprecated in Home Assistant 2026.8)
- `asyncio.timeout` instead of `async_timeout`, `ConfigFlowResult` instead of `FlowResult`
- `PARALLEL_UPDATES` set for sensors (0) and climate (1)
- Removed dead code (unused house selection step, progress step handler, hub device info), unused imports and the wrong `loggers` entry in the manifest

## 1.1.2 (2025-03-19)

### Enhancements
- **Improved API Efficiency**: Removed redundant API calls by optimizing the data update process through the coordinator
- **Immediate Updates**: Climate entities now trigger an immediate data refresh after temperature changes for consistent state across all entities
- **Better Logging**: Added detailed data logging in the coordinator for improved debugging capabilities

### Bug Fixes
- **Error Handling**: Fixed error "could not convert string to float" for non-numeric sensor values like "kein Sensor vorhanden"
- **Sensor Availability**: Non-numeric values for temperature/humidity sensors now correctly mark the entity as unavailable instead of failing
- **Mode Sensor Improvements**: Made the operation mode sensor more robust with better data handling

### Under the Hood
- **Code Optimization**: Streamlined the entity update process to minimize server requests
- **Better Error Reporting**: More detailed error information in logs
- **Coordinator Improvements**: Enhanced the DataUpdateCoordinator with better timing metrics 