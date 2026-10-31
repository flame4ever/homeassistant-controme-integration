"""Minimal Home Assistant, aiohttp and voluptuous stubs for the offline tests.

Only what the Controme modules use is modelled; everything else is a dummy class,
so the package can be imported without Home Assistant installed.
"""
import enum
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class _DummyMeta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return name


class Dummy(metaclass=_DummyMeta):
    """Stand-in for any HA class: subclassable, subscriptable, callable."""

    def __init__(self, *args, **kwargs):
        pass

    def __class_getitem__(cls, item):
        return cls

    def __init_subclass__(cls, **kwargs):
        pass


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = type(name, (Dummy,), {})
        setattr(self, name, value)
        return value


class HVACMode(enum.StrEnum):
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"


class HVACAction(enum.StrEnum):
    OFF = "off"
    HEATING = "heating"
    COOLING = "cooling"
    IDLE = "idle"


class HomeAssistantError(Exception):
    """Like the HA 2026.9.1 exception: translation_* keyword arguments."""

    def __init__(self, *args, translation_domain=None, translation_key=None,
                 translation_placeholders=None):
        if not args and translation_key and translation_domain:
            args = (translation_key,)
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


class ServiceValidationError(HomeAssistantError):
    pass


class ClientError(Exception):
    pass


class ClientTimeout:
    def __init__(self, total=None):
        self.total = total


class Invalid(Exception):
    """voluptuous.Invalid"""


class CoordinatorEntity:
    def __init__(self, coordinator, context=None):
        self.coordinator = coordinator
        self.hass = getattr(coordinator, "hass", None)
        self.writes = 0

    @property
    def available(self):
        return self.coordinator.last_update_success

    async def async_added_to_hass(self):
        pass

    def async_on_remove(self, func):
        pass

    def async_write_ha_state(self):
        self.writes += 1


class FakeResponse:
    def __init__(self, status=200, text="", payload=None):
        self.status = status
        self._text = text
        self._payload = payload

    async def text(self):
        return self._text

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records requests; responses come from a list (or callables raising errors)."""

    def __init__(self):
        self.posts = []
        self.gets = []
        self.post_responses = []
        self.get_responses = []

    def _next(self, responses):
        response = responses.pop(0) if responses else FakeResponse()
        if isinstance(response, BaseException):
            raise response
        return response

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append({"url": url, "data": dict(data or {}), "timeout": timeout})
        return self._next(self.post_responses)

    def get(self, url, timeout=None):
        self.gets.append(url)
        return self._next(self.get_responses)


SESSION = FakeSession()

_MODULES = [
    "homeassistant", "homeassistant.config_entries", "homeassistant.core",
    "homeassistant.const", "homeassistant.exceptions", "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client", "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.device_registry", "homeassistant.helpers.selector",
    "homeassistant.helpers.config_validation", "homeassistant.helpers.entity",
    "homeassistant.helpers.event", "homeassistant.helpers.service",
    "homeassistant.components", "homeassistant.components.climate",
    "homeassistant.components.sensor", "homeassistant.components.binary_sensor",
    "homeassistant.util", "homeassistant.util.dt", "voluptuous", "aiohttp",
]


def install(time_zone):
    """Install the stubs in sys.modules and make the repository importable."""
    for name in _MODULES:
        sys.modules[name] = _StubModule(name)
    for name in _MODULES:
        parent, _, child = name.rpartition(".")
        if parent:
            setattr(sys.modules[parent], child, sys.modules[name])
    modules = sys.modules
    modules["homeassistant.core"].callback = lambda func: func
    modules["homeassistant.const"].ATTR_TEMPERATURE = "temperature"
    modules["homeassistant.exceptions"].HomeAssistantError = HomeAssistantError
    modules["homeassistant.exceptions"].ServiceValidationError = ServiceValidationError
    modules["homeassistant.components.climate"].HVACMode = HVACMode
    modules["homeassistant.components.climate"].HVACAction = HVACAction
    modules["homeassistant.components.climate"].DOMAIN = "climate"
    modules["homeassistant.helpers.update_coordinator"].CoordinatorEntity = CoordinatorEntity
    modules["homeassistant.helpers.device_registry"].DeviceInfo = dict
    modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = lambda hass: SESSION
    modules["homeassistant.helpers.config_validation"].config_entry_only_config_schema = lambda d: None
    modules["homeassistant.helpers.service"].registered = []
    modules["homeassistant.helpers.service"].async_register_platform_entity_service = (
        lambda hass, domain, name, **kwargs: modules["homeassistant.helpers.service"].registered.append(
            (domain, name, kwargs))
    )
    modules["homeassistant.util.dt"].get_default_time_zone = lambda: time_zone
    modules["homeassistant.config_entries"].ConfigFlow = type(
        "ConfigFlow", (Dummy,), {"__init_subclass__": classmethod(lambda cls, **kw: None)}
    )
    modules["aiohttp"].ClientError = ClientError
    modules["aiohttp"].ClientSession = type("ClientSession", (), {})
    modules["aiohttp"].ClientTimeout = ClientTimeout
    vol = modules["voluptuous"]
    vol.Invalid = Invalid
    vol.Required = lambda key, **kwargs: key
    vol.Optional = lambda key, **kwargs: key
    vol.All = lambda *validators: validators
    vol.Schema = lambda schema, **kwargs: schema
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
