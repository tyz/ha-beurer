"""Unit tests for integration setup and unload lifecycle."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BLEDevice
from custom_components.beurer import async_setup_entry, async_unload_entry
from custom_components.beurer.const import DOMAIN
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.exceptions import ConfigEntryNotReady


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.fixture
def mock_entry() -> ConfigEntry:
    """Return a mock ConfigEntry."""
    return ConfigEntry(entry_id="test_entry_id", data={CONF_MAC: "57:4C:42:80:71:BA", "name": "TL100"})


@pytest.mark.asyncio
async def test_async_setup_entry_device_not_found_raises_config_entry_not_ready(
    mock_hass: MagicMock, mock_entry: ConfigEntry
) -> None:
    """Test that setup raises ConfigEntryNotReady when device is not in range."""
    with (
        patch.object(bluetooth, "async_ble_device_from_address", return_value=None),
        pytest.raises(ConfigEntryNotReady),
    ):
        await async_setup_entry(mock_hass, mock_entry)


@pytest.mark.asyncio
async def test_async_setup_entry_success(mock_hass: MagicMock, mock_entry: ConfigEntry) -> None:
    """Test successful setup when device is discovered."""
    fake_ble_device = BLEDevice("57:4C:42:80:71:BA", "TL100_71BA")
    with patch.object(bluetooth, "async_ble_device_from_address", return_value=fake_ble_device):
        result = await async_setup_entry(mock_hass, mock_entry)
        assert result is True
        assert DOMAIN in mock_hass.data
        assert "test_entry_id" in mock_hass.data[DOMAIN]
        mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(mock_entry, ["light"])


@pytest.mark.asyncio
async def test_async_unload_entry(mock_hass: MagicMock, mock_entry: ConfigEntry) -> None:
    """Test unloading integration disconnects BeurerInstance."""
    mock_instance = MagicMock()
    mock_instance.disconnect = AsyncMock()
    mock_hass.data = {DOMAIN: {mock_entry.entry_id: mock_instance}}

    result = await async_unload_entry(mock_hass, mock_entry)
    assert result is True
    assert mock_entry.entry_id not in mock_hass.data[DOMAIN]
    mock_instance.disconnect.assert_awaited_once()
