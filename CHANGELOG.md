# Changelog

## Unreleased

### Bug Fixes
- **Offset Sensors**: Values of 0 and negative values (e.g. total offset) no longer mark the sensor as unavailable
- **Entity IDs**: Room names with umlauts or special characters (e.g. "Küche", "Bad/WC") now produce valid entity IDs
- **Rooms Without ID**: Fixed a crash during setup when a room has no ID
- **Floor as Room**: Entities created from floors without rooms now receive updates
- **Removed Rooms**: Entities become unavailable when their room disappears from the API data
- **Climate HVAC Mode**: Removed the non-functional "Off" mode; the mode is always "Heat" instead of an invalid state
- **Set Temperature Errors**: Failures (wrong credentials, connection errors) are now shown in the UI, and the request has a timeout
- **Return Sensors**: Return temperatures are reported as numbers
- **Config Flow**: The same Controme system can no longer be added twice; the connection test uses Home Assistant's HTTP session and no longer sends misleading Basic Auth

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