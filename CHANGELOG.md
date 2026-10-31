# Changelog

## 2.3.0 (2026-10-31)

### New Features
- **Scenes** (#4): New service `controme.activate_scene` on the Controme climate entities (scene ID, optional approximate duration 1-1440 minutes). For safety only scenes that contain exactly the room of the selected entity are activated: the scene list is read first, the listed room is matched by its name "Floor / Room", and scenes for several rooms (e.g. "*"), unknown scenes, other rooms or ambiguous room names are refused with a translated error before anything is sent. The request always contains the room ID, but Controme applies a scene to all rooms it lists regardless of the room ID, so the protection of other rooms relies only on this check; if Controme reports that other rooms were affected, an error and a warning with the room names follow. There are no scene entities.

### Under the Hood
- The single-room write guard also accepts scene writes, but only with a numeric scene ID and a purely numeric `room_id`; paths are matched exactly (no trailing characters).
- The refresh after a scene is delayed like after a temporary temperature.
- Offline tests with a counting mock show that no request is sent for refused scenes.
- Existing entity IDs, unique IDs and values are unchanged.

## 2.2.0 (2026-10-31)

### New Features
- **Temporary Temperature** (#3): New service `controme.set_temporary_temperature` for Controme climate entities (temperature 5-30 °C in steps of 0.5, optional duration 1-1440 minutes, otherwise the Controme default duration). The new value is shown right away and confirmed by a refresh about 10 seconds later. The duration is only approximate, a normal `climate.set_temperature` ends the temporary value, and the API reports no status of the temporary mode (the attributes `temporary_mode`, `temporary_until` and `permanent_target_temperature` only appear if a firmware reports these documented fields).

### Changes
- **Errors**: All errors are translated (English and German), including wrong credentials ("Authentication failed"), failed writes and the rejected HVAC mode change.
- **Config Flow**: The fields API URL, username and password have descriptions; the password description says that the credentials are only checked when something is written.
- **Documentation**: README section on removing the integration.
- **Brand**: The integration ships its own `brand/` folder (icon and logo, the same files as in the home-assistant/brands repository), as now expected by HACS and preferred by Home Assistant 2026.3 and newer.
- The HVAC mode stays read only as in 2.1.0. Existing entity IDs, unique IDs and values are unchanged.

### Not Included (removed after the live test)
- **Switching the HVAC mode** (#4, #22): The tested firmware rejects the documented call `POST /rooms/{room}/` with `action=betriebsart` (HTTP 400 "please check the url"). The feature was removed completely; it will only come back with a confirmed working API call.
- **Activating scenes** (#4): After a scene call with `room_id`, Controme answered with the list of all rooms, so it apparently does not reliably apply the scene to a single room. Because a scene for all rooms is too risky, the service was removed completely.

### Under the Hood
- Central write helper for set_temperature and the temporary temperature with form encoding, timeout and error mapping. It only sends writes for exactly one room (checked relative to the configured base URL, so URLs with a path prefix work) and refuses everything else with a translated error before sending. Credentials are never logged.
- The service is registered in `async_setup` and checks that the config entry is loaded; `services.yaml` with selectors and translations.
- Offline tests for URLs, request bodies, the single-room guard (with and without path prefix), error mapping, the delayed refresh and service limits (`tests/test_write_actions.py`).

## 2.1.0 (2026-10-30)

### New Features
- **Transmission Monitoring** (#21): The Controme hub device gets three diagnostic entities: "Last transmission" (newest transmission of all sensors), "Stale sensors" (number of sensors without a transmission within the threshold) and the problem binary sensor "Transmission problem" with the attributes `threshold_minutes` and `stale_sensors` (up to 20 sensors, oldest first). The values are recalculated every minute, so the flag also turns on while the Controme system cannot be reached. The entity IDs are fixed and language independent: `sensor.controme_last_transmission`, `sensor.controme_stale_sensors` and `binary_sensor.controme_transmission_problem`.
- **Options**: The threshold for stale sensors can be set under Configure (5-1440 minutes, default 15). Existing entries use the default; stored values below 5 are treated as 5, so the flag does not flicker because of the minute resolution of Controme.

### Notes
- **Room Temperature Sensor** (#5): No change needed. The current temperature of a room already is the value of the sensor that Controme marks as room temperature sensor (also for virtual sensors); this was checked on a live system for all rooms.
- Controme reports local time without a time zone; the Home Assistant time zone must match the Controme system (see README). The behavior in the repeated and the skipped hour of the daylight saving time change is covered by offline tests (`tests/test_transmission.py`, need the tz database, e.g. the `tzdata` package on Windows, otherwise they are skipped).
- Purely additive: existing entities, entity IDs, unique IDs and values are unchanged.

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