"""Device registry helpers for the Controme integration."""
from __future__ import annotations

from homeassistant.const import MAJOR_VERSION, MINOR_VERSION
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

# `via_device` was dropped from `DeviceInfo` in Home Assistant 2026.8 and is
# deprecated in `async_get_or_create` (removal in 2027.8) in favour of
# `via_device_id`, which takes the device registry id of the parent device.
SUPPORTS_VIA_DEVICE_ID = (MAJOR_VERSION, MINOR_VERSION) >= (2026, 8)


def link_to_hub(
    device_info: DeviceInfo, hub_device_id: str | None, house_id: str
) -> DeviceInfo:
    """Link a room device to the Controme hub device."""
    if SUPPORTS_VIA_DEVICE_ID:
        if hub_device_id is not None:
            device_info["via_device_id"] = hub_device_id
    else:
        device_info["via_device"] = (DOMAIN, house_id)  # type: ignore[typeddict-unknown-key]
    return device_info
