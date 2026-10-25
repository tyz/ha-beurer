"""Unit tests for BeurerLight entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_WHITE,
    ColorMode,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError

from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.const import DOMAIN
from custom_components.beurer.light import SCAN_INTERVAL, BeurerLight, async_setup_entry


@pytest.fixture
def mock_instance() -> MagicMock:
    """Return a mock BeurerInstance."""
    instance = MagicMock(spec=BeurerInstance)
    instance.mac = "57:4C:42:80:71:BA"
    instance.is_on = True
    # Mirror the real BeurerInstance property: a lamp is only available while
    # an active BLE connection exists.
    type(instance).available = property(lambda self: bool(self.is_connected))
    instance.color_mode = ColorMode.WHITE
    instance.white_brightness = 200
    instance.color_brightness = 100
    instance.rgb_color = (255, 0, 0)
    instance.effect = "Off"
    instance.supported_effects = ["Off", "Random", "Rainbow"]
    instance.set_white = AsyncMock()
    instance.set_color = AsyncMock()
    instance.set_color_brightness = AsyncMock()
    instance.set_effect = AsyncMock()
    instance.turn_on = AsyncMock()
    instance.turn_off = AsyncMock()
    instance.update = AsyncMock()
    return instance


def test_entity_properties(mock_instance: MagicMock) -> None:
    """Test light entity basic properties."""
    mock_instance.firmware_version = "1.35"
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    assert light.name == "My Lamp"
    assert light.unique_id == "57:4C:42:80:71:BA"
    assert light.is_on is True
    assert light.brightness == 200
    assert light.should_poll is True
    assert SCAN_INTERVAL.total_seconds() == 60
    assert light.device_info["manufacturer"] == "Beurer"
    assert light.device_info["model"] == "TL 100"
    assert light.device_info["sw_version"] == "1.35"

    mock_instance.firmware_version = None
    light_no_fw = BeurerLight(mock_instance, "My Lamp", "entry_123")
    assert "sw_version" not in light_no_fw.device_info


@pytest.mark.asyncio
async def test_async_turn_on_empty_kwargs(mock_instance: MagicMock) -> None:
    """Test async_turn_on without arguments calls turn_on on instance."""
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on()
    mock_instance.turn_on.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_turn_on_brightness_in_white_mode(mock_instance: MagicMock) -> None:
    """Test brightness adjustment while in white mode routes to set_white."""
    mock_instance.color_mode = ColorMode.WHITE
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_BRIGHTNESS: 150})
    mock_instance.set_white.assert_awaited_once_with(150)
    mock_instance.set_color_brightness.assert_not_called()


@pytest.mark.asyncio
async def test_async_turn_on_brightness_in_rgb_mode(mock_instance: MagicMock) -> None:
    """Test brightness adjustment while in RGB mode routes to set_color_brightness."""
    mock_instance.color_mode = ColorMode.RGB
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_BRIGHTNESS: 150})
    mock_instance.set_color_brightness.assert_awaited_once_with(150)
    mock_instance.set_white.assert_not_called()


@pytest.mark.asyncio
async def test_async_turn_on_color_and_brightness(mock_instance: MagicMock) -> None:
    """Test setting both RGB color and brightness in one turn_on call."""
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_RGB_COLOR: (0, 255, 0), ATTR_BRIGHTNESS: 220})
    mock_instance.set_color.assert_awaited_once_with((0, 255, 0))
    mock_instance.set_color_brightness.assert_awaited_once_with(220)
    mock_instance.set_white.assert_not_called()


@pytest.mark.asyncio
async def test_async_turn_on_effect(mock_instance: MagicMock) -> None:
    """Test setting an effect mode."""
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_EFFECT: "Rainbow"})
    mock_instance.set_effect.assert_awaited_once_with("Rainbow")


@pytest.mark.asyncio
async def test_async_turn_on_with_white_attr(mock_instance: MagicMock) -> None:
    """Test setting white brightness via ATTR_WHITE directly calls set_white."""
    mock_instance.color_mode = ColorMode.RGB
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_WHITE: 180})
    mock_instance.set_white.assert_awaited_once_with(180)
    mock_instance.set_color_brightness.assert_not_called()


@pytest.mark.asyncio
async def test_async_turn_on_color_mode_white_no_brightness(
    mock_instance: MagicMock,
) -> None:
    """Test switching to white mode without explicit brightness uses saved brightness."""
    mock_instance.color_mode = ColorMode.RGB
    mock_instance.white_brightness = 220
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_COLOR_MODE: ColorMode.WHITE})
    mock_instance.set_white.assert_awaited_once_with(220)
    mock_instance.set_color_brightness.assert_not_called()


@pytest.mark.asyncio
async def test_async_turn_on_color_mode_white_with_brightness(
    mock_instance: MagicMock,
) -> None:
    """Test switching to white mode with brightness sets white intensity."""
    mock_instance.color_mode = ColorMode.RGB
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_COLOR_MODE: ColorMode.WHITE, ATTR_BRIGHTNESS: 120})
    mock_instance.set_white.assert_awaited_once_with(120)
    mock_instance.set_color_brightness.assert_not_called()


@pytest.mark.asyncio
async def test_async_turn_on_color_mode_rgb(mock_instance: MagicMock) -> None:
    """Test switching to RGB color mode without explicit color sets default or last color."""
    mock_instance.color_mode = ColorMode.WHITE
    mock_instance._color_on = False
    mock_instance.rgb_color = (128, 64, 255)
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_COLOR_MODE: ColorMode.RGB, ATTR_BRIGHTNESS: 90})
    mock_instance.set_color.assert_awaited_once_with((128, 64, 255))
    mock_instance.set_color_brightness.assert_awaited_once_with(90)


@pytest.mark.asyncio
async def test_async_turn_off(mock_instance: MagicMock) -> None:
    """Test turning off."""
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_off()
    mock_instance.turn_off.assert_awaited_once()


def test_update_callback_updates_device_registry(mock_instance: MagicMock) -> None:
    """Test that update_callback updates the device registry with firmware version."""
    from homeassistant.helpers import device_registry as dr

    mock_hass = MagicMock()
    mock_instance.firmware_version = "V1.35"
    mock_instance.mac = "AA:BB:CC:DD:EE:FF"

    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    light.hass = mock_hass

    dev_reg = dr.async_get(mock_hass)
    device = dev_reg.async_get_or_create(
        config_entry_id="entry_123",
        identifiers={(DOMAIN, "AA:BB:CC:DD:EE:FF")},
        manufacturer="Beurer",
        model="TL 100",
        name="My Lamp",
    )
    assert device.sw_version is None

    with patch.object(light, "async_write_ha_state"):
        light.update_callback()

    assert device.sw_version == "V1.35"


@pytest.mark.asyncio
async def test_async_added_to_hass(mock_instance: MagicMock) -> None:
    """Test async_added_to_hass hooks up callback and triggers reconnect when disconnected."""
    mock_hass = MagicMock()
    mock_instance.is_connected = False
    mock_instance.firmware_version = None

    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    light.hass = mock_hass

    await light.async_added_to_hass()

    mock_instance.register_update_callback.assert_called_once_with(light.update_callback)
    mock_instance.set_update_callback.assert_not_called()
    mock_instance.trigger_reconnect.assert_called_once()


def test_rgb_color_returns_white_in_white_mode(mock_instance: MagicMock) -> None:
    """Test that rgb_color always returns (255, 255, 255) when in ColorMode.WHITE."""
    mock_instance.color_mode = ColorMode.WHITE
    mock_instance.rgb_color = (255, 0, 0)
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")

    # Even though underlying instance had (255, 0, 0), in white mode it must report white
    assert light.color_mode == ColorMode.WHITE
    assert light.rgb_color == (255, 255, 255)

    # When in RGB mode, it reports the active RGB color
    mock_instance.color_mode = ColorMode.RGB
    assert light.color_mode == ColorMode.RGB
    assert light.rgb_color == (255, 0, 0)


@pytest.mark.asyncio
async def test_async_turn_on_bleak_error_raises_home_assistant_error(
    mock_instance: MagicMock,
) -> None:
    """Test that BleakError during async_turn_on is translated to HomeAssistantError."""
    mock_instance.turn_on.side_effect = BleakError("Device communication failed")
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await light.async_turn_on()

    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "communication_error"
    assert exc_info.value.translation_placeholders is not None
    assert exc_info.value.translation_placeholders["name"] == "My Lamp"
    assert "Device communication failed" in exc_info.value.translation_placeholders["error"]


@pytest.mark.asyncio
async def test_async_turn_on_timeout_error_raises_home_assistant_error(
    mock_instance: MagicMock,
) -> None:
    """Test that TimeoutError during async_turn_on is translated to HomeAssistantError."""
    mock_instance.set_white.side_effect = TimeoutError("GATT operation timed out")
    mock_instance.color_mode = ColorMode.WHITE
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await light.async_turn_on(**{ATTR_BRIGHTNESS: 150})

    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "communication_error"
    assert exc_info.value.translation_placeholders is not None
    assert exc_info.value.translation_placeholders["name"] == "My Lamp"


@pytest.mark.asyncio
async def test_async_turn_off_bleak_error_raises_home_assistant_error(
    mock_instance: MagicMock,
) -> None:
    """Test that BleakError during async_turn_off is translated to HomeAssistantError."""
    mock_instance.turn_off.side_effect = BleakError("Failed to disconnect/turn off")
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await light.async_turn_off()

    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "communication_error"
    assert exc_info.value.translation_placeholders is not None
    assert exc_info.value.translation_placeholders["name"] == "My Lamp"
    assert "Failed to disconnect/turn off" in exc_info.value.translation_placeholders["error"]


@pytest.mark.asyncio
async def test_async_turn_off_timeout_error_raises_home_assistant_error(
    mock_instance: MagicMock,
) -> None:
    """Test that TimeoutError during async_turn_off is translated to HomeAssistantError."""
    mock_instance.turn_off.side_effect = TimeoutError("Timeout turning off")
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await light.async_turn_off()

    assert exc_info.value.translation_domain == DOMAIN
    assert exc_info.value.translation_key == "communication_error"


def test_available_tracks_connection(mock_instance: MagicMock) -> None:
    """Test the light is only available while an active BLE connection exists."""
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")

    mock_instance.is_connected = True
    assert light.available is True

    mock_instance.is_connected = False
    assert light.available is False


def test_available_when_disconnected_but_advertising(mock_instance: MagicMock) -> None:
    """Test a disconnected lamp that still advertises is reported as unavailable.

    Advertisement history only proves the lamp exists nearby, not that Home
    Assistant can control it, so it must not be treated as available.
    """
    mock_instance.is_connected = False
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    light.hass = MagicMock()

    with patch(
        "homeassistant.components.bluetooth.async_ble_device_from_address",
        return_value=MagicMock(),
    ):
        assert light.available is False


def test_available_is_false_without_hass(mock_instance: MagicMock) -> None:
    """Test availability does not silently fall back to True without hass."""
    mock_instance.is_connected = False
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    assert light.hass is None
    assert light.available is False


@pytest.mark.asyncio
async def test_async_setup_entry_light(mock_instance: MagicMock) -> None:
    """Test async_setup_entry creates and adds BeurerLight."""
    mock_hass = MagicMock()
    mock_entry = ConfigEntry(entry_id="test_entry_id", data={"name": "Bedroom Lamp"})
    mock_entry.runtime_data = mock_instance

    added_devices: list[BeurerLight] = []

    def mock_add_devices(devices: list[BeurerLight]) -> None:
        added_devices.extend(devices)

    await async_setup_entry(mock_hass, mock_entry, mock_add_devices)

    assert len(added_devices) == 1
    assert added_devices[0].name == "Bedroom Lamp"


@pytest.mark.asyncio
async def test_async_added_to_hass_when_connected(mock_instance: MagicMock) -> None:
    """Test async_added_to_hass calls update when already connected."""
    mock_instance.is_connected = True
    mock_instance.firmware_version = "1.00"

    mock_hass = MagicMock()
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    light.hass = mock_hass

    await light.async_added_to_hass()

    mock_instance.register_update_callback.assert_called_once_with(light.update_callback)
    mock_instance.set_update_callback.assert_not_called()
    mock_instance.update.assert_awaited_once()


def test_async_update_device_info_creates_device_when_missing(
    mock_instance: MagicMock,
) -> None:
    """Test _async_update_device_info registers new device if missing."""
    from homeassistant.helpers import device_registry as dr

    mock_hass = MagicMock()
    mock_instance.firmware_version = "1.20"
    mock_instance.mac = "11:22:33:44:55:66"

    light = BeurerLight(mock_instance, "New Lamp", "entry_new")
    light.hass = mock_hass

    dev_reg = dr.async_get(mock_hass)
    assert dev_reg.async_get_device(identifiers={(DOMAIN, "11:22:33:44:55:66")}) is None

    light._async_update_device_info()

    created_device = dev_reg.async_get_device(identifiers={(DOMAIN, "11:22:33:44:55:66")})
    assert created_device is not None
    assert created_device.sw_version == "1.20"


def test_light_properties_rgb_mode(mock_instance: MagicMock) -> None:
    """Test properties in RGB color mode."""
    mock_instance.color_mode = ColorMode.RGB
    mock_instance.color_brightness = 175
    mock_instance.rgb_color = None
    mock_instance.effect = "Rainbow"
    mock_instance.supported_effects = ["Off", "Rainbow"]

    light = BeurerLight(mock_instance, "RGB Lamp", "entry_rgb")

    assert light.brightness == 175
    assert light.rgb_color is None
    assert light.effect == "Rainbow"
    assert light.effect_list == ["Off", "Rainbow"]
    assert light.supported_features == LightEntityFeature.EFFECT

    mock_instance.color_mode = ColorMode.WHITE
    assert light.effect == "Off"


def test_transform_color_brightness(mock_instance: MagicMock) -> None:
    """Test _transform_color_brightness scales RGB color correctly."""
    light = BeurerLight(mock_instance, "Lamp", "entry_1")
    scaled = light._transform_color_brightness((255, 128, 0), 128)
    assert scaled == (128, 64, 0)


@pytest.mark.asyncio
async def test_async_turn_on_with_white_attr_booleans(mock_instance: MagicMock) -> None:
    """Test async_turn_on with boolean values for ATTR_WHITE."""
    mock_instance.white_brightness = 210
    light = BeurerLight(mock_instance, "Lamp", "entry_1")

    await light.async_turn_on(**{ATTR_WHITE: True})
    mock_instance.set_white.assert_awaited_with(210)

    await light.async_turn_on(**{ATTR_WHITE: False})
    mock_instance.set_white.assert_awaited_with(0)


@pytest.mark.asyncio
async def test_async_update(mock_instance: MagicMock) -> None:
    """Test async_update forwards call to BeurerInstance.update."""
    light = BeurerLight(mock_instance, "Lamp", "entry_1")
    await light.async_update()
    mock_instance.update.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_turn_on_effect_applies_brightness_to_color_channel(
    mock_instance: MagicMock,
) -> None:
    """Test combining an effect with brightness keeps the effect on the colour channel.

    The README documents ``effect`` together with ``brightness_pct``. Applying
    the brightness before the effect sent it to the daylight channel, which the
    effect then switched off, so the requested brightness was silently lost.
    """
    mock_instance.color_mode = ColorMode.WHITE
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")

    await light.async_turn_on(**{ATTR_EFFECT: "Rainbow", ATTR_BRIGHTNESS: 102})

    mock_instance.set_effect.assert_awaited_once_with("Rainbow")
    mock_instance.set_color_brightness.assert_awaited_once_with(102)
    mock_instance.set_white.assert_not_called()
