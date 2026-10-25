"""Unit tests for Beurer diagnostics platform."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.components.light import ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC

from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.diagnostics import async_get_config_entry_diagnostics


@pytest.fixture
def mock_entry() -> ConfigEntry:
    """Return a mock ConfigEntry."""
    return ConfigEntry(
        entry_id="test_entry_id",
        data={CONF_MAC: "57:4C:42:80:71:BA", "name": "TL 100 Bedroom"},
        title="TL 100 Bedroom",
    )


@pytest.fixture
def mock_instance() -> MagicMock:
    """Return a mock BeurerInstance."""
    instance = MagicMock(spec=BeurerInstance)
    instance.mac = "57:4C:42:80:71:BA"
    instance.is_connected = True
    instance.firmware_version = "1.35"
    instance.is_on = True
    instance._light_on = True
    instance._color_on = False
    instance.color_mode = ColorMode.WHITE
    instance.white_brightness = 200
    instance.color_brightness = None
    instance.rgb_color = (255, 255, 255)
    instance.effect = "Off"
    instance.supported_effects = ["Off", "Random", "Rainbow"]
    instance.timer_duration = 15
    instance.timer_active = False
    instance.timer_minutes_remaining = 0
    instance._last_notification_cmd = 0xE8
    instance._last_queried_channel = 1
    instance.is_closing = False
    return instance


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics(mock_entry: ConfigEntry, mock_instance: MagicMock) -> None:
    """Test retrieving diagnostics successfully redacting sensitive MAC."""
    mock_hass = MagicMock()
    mock_entry.runtime_data = mock_instance

    diagnostics = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert "entry" in diagnostics
    assert "device" in diagnostics

    # Verify sensitive data redaction
    assert diagnostics["entry"]["data"][CONF_MAC] == "**REDACTED**"
    assert diagnostics["entry"]["title"] == "TL 100 Bedroom"
    assert diagnostics["device"]["mac"] == "**REDACTED**"

    # Verify device state details
    assert diagnostics["device"]["firmware_version"] == "1.35"
    assert diagnostics["device"]["is_connected"] is True
    assert diagnostics["device"]["is_on"] is True
    assert diagnostics["device"]["white_brightness"] == 200
    assert diagnostics["device"]["last_notification_cmd"] == "0xe8"
    assert diagnostics["device"]["timer_duration"] == 15
    assert diagnostics["device"]["timer_active"] is False
    assert diagnostics["device"]["timer_minutes_remaining"] == 0
    assert diagnostics["device"]["is_closing"] is False


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_when_instance_missing(
    mock_entry: ConfigEntry,
) -> None:
    """Test diagnostics when the entry has no loaded BeurerInstance."""
    mock_hass = MagicMock()
    mock_entry.runtime_data = None

    diagnostics = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert diagnostics["entry"]["data"][CONF_MAC] == "**REDACTED**"
    assert diagnostics["device"] == {}


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics_for_unloaded_entry(
    mock_entry: ConfigEntry,
) -> None:
    """Test diagnostics also work for an entry that never finished setting up.

    ConfigEntry.runtime_data does not exist at all until setup assigns it, so
    reading it directly raised AttributeError. Home Assistant offers the
    download button for failed and disabled entries too, where diagnostics are
    most useful.
    """
    mock_hass = MagicMock()
    assert not hasattr(mock_entry, "runtime_data")

    diagnostics = await async_get_config_entry_diagnostics(mock_hass, mock_entry)

    assert diagnostics["entry"]["data"][CONF_MAC] == "**REDACTED**"
    assert diagnostics["device"] == {}
