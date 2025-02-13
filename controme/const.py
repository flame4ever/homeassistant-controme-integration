"""Constants for the Controme integration."""
from typing import Final

DOMAIN: Final = "controme"

# Configuration Keys (werden in der Webkonfiguration abgefragt)
CONF_API_URL: Final = "api_url"
CONF_HAUS_ID: Final = "haus_id"
CONF_USER: Final = "user"
CONF_PASSWORD: Final = "password"

# Plattform(en) die von der Integration bereitgestellt werden
PLATFORMS: Final = ["climate"] 