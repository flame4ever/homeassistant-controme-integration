import requests
from homeassistant.helpers.entity import Entity

def setup_platform(hass, config, add_entities, discovery_info=None):
    api_url = config.get("api_url")
    haus_id = config.get("haus_id")
    user = config.get("user")
    password = config.get("password")
    add_entities([ContromeSensor(api_url, haus_id, user, password)])

class ContromeSensor(Entity):
    def __init__(self, api_url, haus_id, user, password):
        self._state = None
        self._api_url = api_url
        self._haus_id = haus_id
        self._user = user
        self._password = password

    @property
    def name(self):
        return "Controme Sensor"

    @property
    def state(self):
        return self._state

    def update(self):
        response = requests.get(
            f"{self._api_url}/get/json/v1/{self._haus_id}",
            auth=(self._user, self._password)
        )
        data = response.json()
        self._state = data["dein_datenpunkt"]
        