"""Unit tests for BeurerLight entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.const import DOMAIN
from custom_components.beurer.light import SCAN_INTERVAL, BeurerLight
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_WHITE,
    ColorMode,
)


@pytest.fixture
def mock_instance() -> MagicMock:
    """Return a mock BeurerInstance."""
    instance = MagicMock(spec=BeurerInstance)
    instance.mac = "57:4C:42:80:71:BA"
    instance.is_on = True
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
async def test_async_turn_on_color_mode_white_no_brightness(mock_instance: MagicMock) -> None:
    """Test switching to white mode without explicit brightness uses saved brightness."""
    mock_instance.color_mode = ColorMode.RGB
    mock_instance.white_brightness = 220
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_on(**{ATTR_COLOR_MODE: ColorMode.WHITE})
    mock_instance.set_white.assert_awaited_once_with(220)
    mock_instance.set_color_brightness.assert_not_called()


@pytest.mark.asyncio
async def test_async_turn_on_color_mode_white_with_brightness(mock_instance: MagicMock) -> None:
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

    mock_instance.set_update_callback.assert_called_once_with(light.update_callback)
    mock_instance.trigger_reconnect.assert_called_once()
