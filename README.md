# Controme Integration for Home Assistant

This custom integration allows you to interact with the Controme API to control and monitor climate functionality (e.g., thermostats) for your houses. It dynamically retrieves available house IDs and lets you select one during setup. If only a single house is returned by the API, it will be automatically selected.

## Features

- **Dynamic Configuration:**  
  Enter the API URL, username, and password via the Home Assistant UI. The integration fetches available house IDs from the API.

- **House Selection:**  
  If the API returns multiple house IDs, you will be prompted to choose one. When only one house is found, it is automatically selected.

- **Climate Platform:**  
  Provides a sample climate (thermostat) entity. Customize the climate functionality in `climate.py` as needed.

- **UI-Driven Setup:**  
  No need to modify your `configuration.yaml` manually. The integration supports the Home Assistant Config Flow and is fully configurable from the UI.

## Installation

### Prerequisites

- Home Assistant version 0.105 or later.
- Python 3.9 or later.
- A running instance of the Controme API with valid credentials.

### Steps

1. **Clone or Download the Repository:**

   ```bash
   git clone https://github.com/yourusername/homeassistant-controme-integration.git
   ```

2. **Copy to Custom Components Folder:**

   Place the contents of the repository into the following folder in your Home Assistant configuration:
   
   ```
   /config/custom_components/controme/
   ```

   The folder structure should look like this:
   
   ```
   custom_components/controme/
   ├── __init__.py
   ├── manifest.json
   ├── config_flow.py
   ├── const.py
   ├── climate.py
   └── translations/
       └── en.json
   ```

3. **Restart Home Assistant.**

## Configuration via the Home Assistant UI

Once installed, configure the integration by following these steps:

1. Navigate to **Configuration > Devices & Services > Add Integration**.
2. Search for **Controme** and select it.
3. Enter your API credentials:
   - **API URL:** e.g. `http://192.168.x.x` (must start with `http://` or `https://`)
   - **Username:** Your API username.
   - **Password:** Your API password.
4. The integration will automatically fetch available house IDs from your API endpoint (`{api_url}/houses`).
   - If multiple house IDs are found, you will be prompted to select one.
   - If only one house ID is returned, it will be selected automatically.
5. Complete the flow to create the integration entry.

### Using configuration.yaml (Fallback)

If needed, you can also configure the integration via `configuration.yaml`:
