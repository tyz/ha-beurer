"""Fixtures and Home Assistant mocks for Beurer tests."""

from __future__ import annotations

import enum
import sys
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, MagicMock


def _setup_mock_modules() -> None:
    """Mock external dependencies if not installed in the environment."""
    # Mock voluptuous
    if "voluptuous" not in sys.modules:
        vol_mod = ModuleType("voluptuous")

        class MockSchema:
            def __init__(self, schema: Any = None) -> None:
                self.schema = schema

            def extend(self, extra: Any) -> MockSchema:
                return self

        class MockMarker:
            def __init__(self, key: Any, **kwargs: Any) -> None:
                self.key = key

        vol_mod.Schema = MockSchema  # type: ignore[attr-defined]
        vol_mod.Required = MockMarker  # type: ignore[attr-defined]
        vol_mod.Optional = MockMarker  # type: ignore[attr-defined]
        vol_mod.In = lambda x: x  # type: ignore[attr-defined]
        sys.modules["voluptuous"] = vol_mod

    # Mock bleak
    if "bleak" not in sys.modules:
        bleak_mod = ModuleType("bleak")

        class MockBLEDevice:
            def __init__(self, address: str = "57:4C:42:80:71:BA", name: str = "TL100_71BA") -> None:
                self.address = address
                self.name = name

        class MockBleakError(Exception):
            pass

        class MockBleakGATTCharacteristic:
            def __init__(self, uuid: str = "test-uuid") -> None:
                self.uuid = uuid

        class MockBleakClient:
            def __init__(self, address_or_device: Any, disconnected_callback: Any = None) -> None:
                self.address = getattr(address_or_device, "address", address_or_device)
                self.disconnected_callback = disconnected_callback
                self.is_connected = False
                self.services = MagicMock()
                self.services.characteristics = {}
                self.connect = AsyncMock(return_value=True)
                self.disconnect = AsyncMock(return_value=True)
                self.start_notify = AsyncMock()
                self.write_gatt_char = AsyncMock()

        class MockBleakScanner:
            discover = AsyncMock(return_value=[])

        bleak_mod.BLEDevice = MockBLEDevice  # type: ignore[attr-defined]
        bleak_mod.BleakClient = MockBleakClient  # type: ignore[attr-defined]
        bleak_mod.BleakError = MockBleakError  # type: ignore[attr-defined]
        bleak_mod.BleakGATTCharacteristic = MockBleakGATTCharacteristic  # type: ignore[attr-defined]
        bleak_mod.BleakScanner = MockBleakScanner  # type: ignore[attr-defined]
        sys.modules["bleak"] = bleak_mod

        bleak_exc = ModuleType("bleak.exc")
        bleak_exc.BleakError = MockBleakError  # type: ignore[attr-defined]
        sys.modules["bleak.exc"] = bleak_exc

    # Mock bleak_retry_connector
    if "bleak_retry_connector" not in sys.modules:
        brc_mod = ModuleType("bleak_retry_connector")

        class MockBleakClientWithServiceCache(sys.modules["bleak"].BleakClient):  # type: ignore[misc]
            pass

        class MockBleakConnectionError(Exception):
            pass

        async def mock_establish_connection(
            client_class: Any, device: Any, name: str, disconnected_callback: Any = None, **kwargs: Any
        ) -> Any:
            client = client_class(device, disconnected_callback=disconnected_callback)
            client.is_connected = True
            return client

        brc_mod.BleakClientWithServiceCache = MockBleakClientWithServiceCache  # type: ignore[attr-defined]
        brc_mod.BleakConnectionError = MockBleakConnectionError  # type: ignore[attr-defined]
        brc_mod.establish_connection = mock_establish_connection  # type: ignore[attr-defined]
        sys.modules["bleak_retry_connector"] = brc_mod

    # Mock homeassistant
    if "homeassistant" not in sys.modules:
        ha_mod = ModuleType("homeassistant")
        sys.modules["homeassistant"] = ha_mod

        # core
        ha_core = ModuleType("homeassistant.core")
        ha_core.HomeAssistant = MagicMock()  # type: ignore[attr-defined]

        def callback(func: Any) -> Any:
            return func

        ha_core.callback = callback  # type: ignore[attr-defined]
        ha_core.Event = MagicMock()  # type: ignore[attr-defined]
        sys.modules["homeassistant.core"] = ha_core

        # const
        ha_const = ModuleType("homeassistant.const")
        ha_const.CONF_MAC = "mac"  # type: ignore[attr-defined]
        ha_const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"  # type: ignore[attr-defined]

        class Platform(str, enum.Enum):
            LIGHT = "light"
            NUMBER = "number"
            SWITCH = "switch"
            SENSOR = "sensor"

        class UnitOfTime(str, enum.Enum):
            MINUTES = "min"
            SECONDS = "s"

        ha_const.Platform = Platform  # type: ignore[attr-defined]
        ha_const.UnitOfTime = UnitOfTime  # type: ignore[attr-defined]
        sys.modules["homeassistant.const"] = ha_const

        # exceptions
        ha_exc = ModuleType("homeassistant.exceptions")

        class ConfigEntryNotReady(Exception):
            pass

        class HomeAssistantError(Exception):
            def __init__(
                self,
                *args: Any,
                translation_domain: str | None = None,
                translation_key: str | None = None,
                translation_placeholders: dict[str, str] | None = None,
            ) -> None:
                super().__init__(*args)
                self.translation_domain = translation_domain
                self.translation_key = translation_key
                self.translation_placeholders = translation_placeholders

        ha_exc.ConfigEntryNotReady = ConfigEntryNotReady  # type: ignore[attr-defined]
        ha_exc.HomeAssistantError = HomeAssistantError  # type: ignore[attr-defined]
        sys.modules["homeassistant.exceptions"] = ha_exc

        # data_entry_flow
        ha_def = ModuleType("homeassistant.data_entry_flow")
        ha_def.FlowResult = dict[str, Any]  # type: ignore[attr-defined]

        class AbortFlow(Exception):
            def __init__(self, reason: str, **kwargs: Any) -> None:
                super().__init__(reason)
                self.reason = reason

        ha_def.AbortFlow = AbortFlow  # type: ignore[attr-defined]
        sys.modules["homeassistant.data_entry_flow"] = ha_def

        # config_entries
        ha_ce = ModuleType("homeassistant.config_entries")

        class ConfigEntry:
            def __init__(
                self,
                entry_id: str = "test_entry",
                data: dict[str, Any] | None = None,
                version: int = 1,
                domain: str = "beurer",
                title: str = "Beurer",
            ) -> None:
                self.entry_id = entry_id
                self.data = data or {}
                self.version = version
                self.domain = domain
                self.title = title

            def async_on_unload(self, func: Any) -> None:
                pass

        class ConfigFlow:
            _domain: str | None = None

            def __init__(self) -> None:
                self.context: dict[str, Any] = {}
                self._unique_id: str | None = None

            def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
                super().__init_subclass__(**kwargs)
                cls._domain = domain

            async def async_set_unique_id(self, unique_id: str) -> None:
                self._unique_id = unique_id

            def _abort_if_unique_id_configured(self) -> None:
                if self._unique_id and self._unique_id in self._async_current_ids():
                    raise AbortFlow("already_configured")

            def _set_confirm_only(self) -> None:
                pass

            def _async_current_ids(self, include_ignore: bool = False) -> set[str]:
                return set()

            def async_show_form(
                self,
                step_id: str,
                data_schema: Any = None,
                errors: dict[str, str] | None = None,
                description_placeholders: dict[str, str] | None = None,
            ) -> dict[str, Any]:
                return {
                    "type": "form",
                    "step_id": step_id,
                    "data_schema": data_schema,
                    "errors": errors or {},
                    "description_placeholders": description_placeholders or {},
                }

            def async_create_entry(self, title: str, data: dict[str, Any]) -> dict[str, Any]:
                return {"type": "create_entry", "title": title, "data": data}

            def async_abort(self, reason: str) -> dict[str, Any]:
                return {"type": "abort", "reason": reason}

        ha_ce.ConfigEntry = ConfigEntry  # type: ignore[attr-defined]
        ha_ce.ConfigFlow = ConfigFlow  # type: ignore[attr-defined]
        sys.modules["homeassistant.config_entries"] = ha_ce

        # components
        ha_comp = ModuleType("homeassistant.components")
        sys.modules["homeassistant.components"] = ha_comp

        # components.diagnostics
        ha_diag = ModuleType("homeassistant.components.diagnostics")

        def async_redact_data(data: dict[str, Any], to_redact: Any) -> dict[str, Any]:
            redacted: dict[str, Any] = {}
            for key, val in data.items():
                if key in to_redact:
                    redacted[key] = "**REDACTED**"
                elif isinstance(val, dict):
                    redacted[key] = async_redact_data(val, to_redact)
                else:
                    redacted[key] = val
            return redacted

        ha_diag.async_redact_data = async_redact_data  # type: ignore[attr-defined]
        sys.modules["homeassistant.components.diagnostics"] = ha_diag

        # components.bluetooth
        ha_bt = ModuleType("homeassistant.components.bluetooth")
        ha_bt.async_ble_device_from_address = MagicMock(return_value=None)  # type: ignore[attr-defined]
        ha_bt.async_register_callback = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
        ha_bt.async_track_unavailable = MagicMock(return_value=MagicMock())  # type: ignore[attr-defined]
        ha_bt.BluetoothCallbackMatcher = MagicMock()  # type: ignore[attr-defined]
        ha_bt.BluetoothScanningMode = MagicMock()  # type: ignore[attr-defined]
        ha_bt.BluetoothServiceInfoBleak = MagicMock()  # type: ignore[attr-defined]
        ha_bt.BluetoothChange = MagicMock()  # type: ignore[attr-defined]
        sys.modules["homeassistant.components.bluetooth"] = ha_bt

        # components.light
        ha_light = ModuleType("homeassistant.components.light")

        class ColorMode(str, enum.Enum):
            WHITE = "white"
            RGB = "rgb"

        class LightEntityFeature(enum.IntFlag):
            EFFECT = 4

        class LightEntity:
            hass: Any = None
            _attr_name: str | None = None
            _attr_unique_id: str | None = None
            _attr_supported_color_modes: set[ColorMode] | None = None

            def async_write_ha_state(self) -> None:
                pass

            @property
            def name(self) -> str | None:
                return self._attr_name

            @property
            def unique_id(self) -> str | None:
                return self._attr_unique_id

        ha_light.ColorMode = ColorMode  # type: ignore[attr-defined]
        ha_light.LightEntityFeature = LightEntityFeature  # type: ignore[attr-defined]
        ha_light.LightEntity = LightEntity  # type: ignore[attr-defined]
        ha_light.ATTR_RGB_COLOR = "rgb_color"  # type: ignore[attr-defined]
        ha_light.ATTR_BRIGHTNESS = "brightness"  # type: ignore[attr-defined]
        ha_light.ATTR_EFFECT = "effect"  # type: ignore[attr-defined]
        ha_light.ATTR_WHITE = "white"  # type: ignore[attr-defined]
        ha_light.ATTR_COLOR_MODE = "color_mode"  # type: ignore[attr-defined]

        class MockPlatformSchema:
            def extend(self, extra: Any) -> MockPlatformSchema:
                return self

        ha_light.PLATFORM_SCHEMA = MockPlatformSchema()  # type: ignore[attr-defined]
        sys.modules["homeassistant.components.light"] = ha_light

        # components.number
        ha_number = ModuleType("homeassistant.components.number")

        class NumberMode(str, enum.Enum):
            AUTO = "auto"
            BOX = "box"
            SLIDER = "slider"

        class NumberEntity:
            hass: Any = None
            _attr_has_entity_name: bool = False
            _attr_translation_key: str | None = None
            _attr_unique_id: str | None = None
            _attr_native_value: float | None = None
            _attr_native_min_value: float = 0.0
            _attr_native_max_value: float = 100.0
            _attr_native_step: float = 1.0
            _attr_native_unit_of_measurement: str | None = None
            _attr_mode: NumberMode | str = NumberMode.AUTO

            def async_write_ha_state(self) -> None:
                pass

            @property
            def unique_id(self) -> str | None:
                return self._attr_unique_id

            @property
            def translation_key(self) -> str | None:
                return self._attr_translation_key

            @property
            def has_entity_name(self) -> bool:
                return self._attr_has_entity_name

            @property
            def native_value(self) -> float | None:
                return self._attr_native_value

            @property
            def native_min_value(self) -> float:
                return self._attr_native_min_value

            @property
            def native_max_value(self) -> float:
                return self._attr_native_max_value

            @property
            def native_step(self) -> float:
                return self._attr_native_step

            @property
            def native_unit_of_measurement(self) -> str | None:
                return self._attr_native_unit_of_measurement

            @property
            def mode(self) -> str:
                return str(self._attr_mode)

            async def async_set_native_value(self, value: float) -> None:
                raise NotImplementedError

        ha_number.NumberEntity = NumberEntity  # type: ignore[attr-defined]
        ha_number.NumberMode = NumberMode  # type: ignore[attr-defined]
        sys.modules["homeassistant.components.number"] = ha_number

        # components.switch
        ha_switch = ModuleType("homeassistant.components.switch")

        class SwitchEntity:
            hass: Any = None
            _attr_has_entity_name: bool = False
            _attr_translation_key: str | None = None
            _attr_unique_id: str | None = None
            _attr_is_on: bool | None = None

            def async_write_ha_state(self) -> None:
                pass

            @property
            def unique_id(self) -> str | None:
                return self._attr_unique_id

            @property
            def translation_key(self) -> str | None:
                return self._attr_translation_key

            @property
            def has_entity_name(self) -> bool:
                return self._attr_has_entity_name

            @property
            def is_on(self) -> bool | None:
                return self._attr_is_on

            async def async_turn_on(self, **kwargs: Any) -> None:
                raise NotImplementedError

            async def async_turn_off(self, **kwargs: Any) -> None:
                raise NotImplementedError

        ha_switch.SwitchEntity = SwitchEntity  # type: ignore[attr-defined]
        sys.modules["homeassistant.components.switch"] = ha_switch

        # components.sensor
        ha_sensor = ModuleType("homeassistant.components.sensor")

        class SensorDeviceClass(str, enum.Enum):
            DURATION = "duration"

        class SensorStateClass(str, enum.Enum):
            MEASUREMENT = "measurement"
            TOTAL = "total"
            TOTAL_INCREASING = "total_increasing"

        class SensorEntity:
            hass: Any = None
            _attr_has_entity_name: bool = False
            _attr_translation_key: str | None = None
            _attr_unique_id: str | None = None
            _attr_native_value: Any = None
            _attr_native_unit_of_measurement: str | None = None
            _attr_device_class: SensorDeviceClass | None = None
            _attr_state_class: SensorStateClass | None = None

            def async_write_ha_state(self) -> None:
                pass

            @property
            def unique_id(self) -> str | None:
                return self._attr_unique_id

            @property
            def translation_key(self) -> str | None:
                return self._attr_translation_key

            @property
            def has_entity_name(self) -> bool:
                return self._attr_has_entity_name

            @property
            def native_value(self) -> Any:
                return self._attr_native_value

            @property
            def native_unit_of_measurement(self) -> str | None:
                return self._attr_native_unit_of_measurement

            @property
            def device_class(self) -> SensorDeviceClass | None:
                return self._attr_device_class

            @property
            def state_class(self) -> SensorStateClass | None:
                return self._attr_state_class

        ha_sensor.SensorEntity = SensorEntity  # type: ignore[attr-defined]
        ha_sensor.SensorDeviceClass = SensorDeviceClass  # type: ignore[attr-defined]
        ha_sensor.SensorStateClass = SensorStateClass  # type: ignore[attr-defined]
        sys.modules["homeassistant.components.sensor"] = ha_sensor

        # helpers
        ha_help = ModuleType("homeassistant.helpers")
        sys.modules["homeassistant.helpers"] = ha_help

        ha_cv = ModuleType("homeassistant.helpers.config_validation")
        ha_cv.string = str  # type: ignore[attr-defined]
        sys.modules["homeassistant.helpers.config_validation"] = ha_cv

        ha_dr = ModuleType("homeassistant.helpers.device_registry")

        class DeviceInfo(dict[str, Any]):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)

        def format_mac(mac: str) -> str:
            return mac.lower().replace(":", "")

        class DeviceEntry:
            def __init__(
                self,
                id: str = "mock_device_id",
                identifiers: set[tuple[str, str]] | None = None,
                sw_version: str | None = None,
                manufacturer: str | None = None,
                model: str | None = None,
                name: str | None = None,
                **kwargs: Any,
            ) -> None:
                self.id = id
                self.identifiers = identifiers or set()
                self.sw_version = sw_version
                self.manufacturer = manufacturer
                self.model = model
                self.name = name
                for key, val in kwargs.items():
                    setattr(self, key, val)

        class MockDeviceRegistry:
            def __init__(self) -> None:
                self.devices: dict[str, DeviceEntry] = {}

            def async_get_device(self, identifiers: set[tuple[str, str]]) -> DeviceEntry | None:
                for device in self.devices.values():
                    if device.identifiers & identifiers:
                        return device
                return None

            def async_update_device(self, device_id: str, **kwargs: Any) -> DeviceEntry | None:
                device = self.devices.get(device_id)
                if device:
                    for key, val in kwargs.items():
                        setattr(device, key, val)
                return device

            def async_get_or_create(self, **kwargs: Any) -> DeviceEntry:
                identifiers = kwargs.get("identifiers", set())
                device = self.async_get_device(identifiers)
                if device:
                    self.async_update_device(device.id, **kwargs)
                    return device
                dev_id = f"dev_{len(self.devices) + 1}"
                new_device = DeviceEntry(id=dev_id, **kwargs)
                self.devices[dev_id] = new_device
                return new_device

        _mock_dr_instance = MockDeviceRegistry()

        def async_get(hass: Any) -> MockDeviceRegistry:
            return _mock_dr_instance

        ha_dr.DeviceInfo = DeviceInfo  # type: ignore[attr-defined]
        ha_dr.DeviceEntry = DeviceEntry  # type: ignore[attr-defined]
        ha_dr.DeviceRegistry = MockDeviceRegistry  # type: ignore[attr-defined]
        ha_dr.async_get = async_get  # type: ignore[attr-defined]
        ha_dr.format_mac = format_mac  # type: ignore[attr-defined]
        sys.modules["homeassistant.helpers.device_registry"] = ha_dr

        ha_ep = ModuleType("homeassistant.helpers.entity_platform")
        ha_ep.AddEntitiesCallback = Any  # type: ignore[attr-defined]
        sys.modules["homeassistant.helpers.entity_platform"] = ha_ep

        # util.color
        ha_util = ModuleType("homeassistant.util")
        sys.modules["homeassistant.util"] = ha_util
        ha_color = ModuleType("homeassistant.util.color")

        def match_max_scale(scale: tuple[int, ...], color: tuple[int, ...]) -> tuple[int, ...]:
            return color

        ha_color.match_max_scale = match_max_scale  # type: ignore[attr-defined]
        sys.modules["homeassistant.util.color"] = ha_color


_setup_mock_modules()

from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util

cc_mod = ModuleType("custom_components")
cc_mod.__path__ = []
sys.modules["custom_components"] = cc_mod

spec = importlib.util.spec_from_file_location(
    "custom_components.beurer",
    str(ROOT / "__init__.py"),
    submodule_search_locations=[str(ROOT)],
)
if spec and spec.loader:
    beurer_pkg = importlib.util.module_from_spec(spec)
    sys.modules["custom_components.beurer"] = beurer_pkg
    spec.loader.exec_module(beurer_pkg)


def pytest_configure(config: Any) -> None:
    """Register custom marks."""
    config.addinivalue_line("markers", "asyncio: mark test to run asynchronously")


def pytest_pyfunc_call(pyfuncitem: Any) -> bool | None:
    """Run async test functions with asyncio.run."""
    import asyncio
    import inspect

    if inspect.iscoroutinefunction(pyfuncitem.obj):
        asyncio.run(pyfuncitem.obj(*[pyfuncitem.funcargs[arg] for arg in pyfuncitem._fixtureinfo.argnames]))
        return True
    return None
