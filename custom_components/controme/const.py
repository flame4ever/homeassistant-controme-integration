"""Constants for the Controme integration."""

from typing import Final

# Domain der Integration
DOMAIN: Final = "controme"

# Konfigurationsschlüssel, die in der Webkonfiguration abgefragt werden
CONF_API_URL: Final = "api_url"
CONF_HAUS_ID: Final = "haus_id"
CONF_USER: Final = "user"
CONF_PASSWORD: Final = "password"

# Plattformen, die von der Integration bereitgestellt werden
PLATFORMS: Final = ["climate"]