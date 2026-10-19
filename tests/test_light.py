"""Unit tests for BeurerLight entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.light import BeurerLight
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
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
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    assert light.name == "My Lamp"
    assert light.unique_id == "57:4C:42:80:71:BA"
    assert light.is_on is True
    assert light.brightness == 200
    assert light.device_info["manufacturer"] == "Beurer"
    assert light.device_info["model"] == "TL 100"


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
async def test_async_turn_off(mock_instance: MagicMock) -> None:
    """Test turning off."""
    light = BeurerLight(mock_instance, "My Lamp", "entry_123")
    await light.async_turn_off()
    mock_instance.turn_off.assert_awaited_once()
