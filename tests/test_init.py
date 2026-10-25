"""Unit tests for integration setup and unload lifecycle."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BLEDevice
from custom_components.beurer import PLATFORMS, async_setup_entry, async_unload_entry
from custom_components.beurer.const import DOMAIN
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, Platform
from homeassistant.exceptions import ConfigEntryNotReady


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return a mock HomeAssistant instance."""
    hass = MagicMock()
    hass.data = {}
    hass.bus = MagicMock()
    hass.bus.async_listen_once = MagicMock()
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
        assert Platform.NUMBER in PLATFORMS
        assert Platform.SELECT not in PLATFORMS
        mock_hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(mock_entry, PLATFORMS)


@pytest.mark.asyncio
async def test_async_setup_entry_registers_bluetooth_callback(mock_hass: MagicMock, mock_entry: ConfigEntry) -> None:
    """Test that setup registers a bluetooth callback and updates device on advertisement."""
    fake_ble_device = BLEDevice("57:4C:42:80:71:BA", "TL100_71BA")
    updated_device = BLEDevice("57:4C:42:80:71:BA", "TL100_71BA_UPDATED")

    registered_callback = None

    def mock_register_callback(hass: Any, cb: Any, matcher: Any, mode: Any) -> MagicMock:
        nonlocal registered_callback
        registered_callback = cb
        return MagicMock()

    with (
        patch.object(bluetooth, "async_ble_device_from_address", return_value=fake_ble_device),
        patch.object(bluetooth, "async_register_callback", side_effect=mock_register_callback),
    ):
        result = await async_setup_entry(mock_hass, mock_entry)
        assert result is True
        assert registered_callback is not None

        # Simulate incoming Bluetooth advertisement
        mock_service_info = MagicMock()
        mock_service_info.device = updated_device

        instance = mock_hass.data[DOMAIN][mock_entry.entry_id]
        with patch.object(instance, "trigger_reconnect") as mock_reconnect:
            registered_callback(mock_service_info, MagicMock())
            assert instance._ble_device == updated_device
            mock_reconnect.assert_called_once()

        # Simulate advertisement when already connected (should not trigger reconnect)
        mock_connected_client = MagicMock()
        mock_connected_client.is_connected = True
        instance._device = mock_connected_client
        with patch.object(instance, "trigger_reconnect") as mock_reconnect:
            registered_callback(mock_service_info, MagicMock())
            mock_reconnect.assert_not_called()


@pytest.mark.asyncio
async def test_async_unload_entry(mock_hass: MagicMock, mock_entry: ConfigEntry) -> None:
    """Test unloading integration disconnects BeurerInstance."""
    mock_instance = MagicMock()
    mock_instance.disconnect = AsyncMock()
    mock_hass.data = {DOMAIN: {mock_entry.entry_id: mock_instance}}

    result = await async_unload_entry(mock_hass, mock_entry)
    assert result is True
    assert mock_entry.entry_id not in mock_hass.data[DOMAIN]
    mock_instance.disconnect.assert_awaited_once_with(closing=True)


@pytest.mark.asyncio
async def test_async_setup_entry_registers_stop_listener(mock_hass: MagicMock, mock_entry: ConfigEntry) -> None:
    """Test that setup registers a stop event listener to disconnect on shutdown."""
    fake_ble_device = BLEDevice("57:4C:42:80:71:BA", "TL100_71BA")
    stop_callback = None

    def mock_listen_once(event: str, cb: Any) -> MagicMock:
        nonlocal stop_callback
        if event == "homeassistant_stop":
            stop_callback = cb
        return MagicMock()

    mock_hass.bus.async_listen_once.side_effect = mock_listen_once

    with patch.object(bluetooth, "async_ble_device_from_address", return_value=fake_ble_device):
        result = await async_setup_entry(mock_hass, mock_entry)
        assert result is True
        assert stop_callback is not None

        instance = mock_hass.data[DOMAIN][mock_entry.entry_id]
        with patch.object(instance, "disconnect", new_callable=AsyncMock) as mock_disconnect:
            await stop_callback(MagicMock())
            mock_disconnect.assert_awaited_once_with(closing=True)


@pytest.mark.asyncio
async def test_async_setup_entry_registers_unavailable_tracking(mock_hass: MagicMock, mock_entry: ConfigEntry) -> None:
    """Test that setup registers an unavailable callback which triggers entity update on timeout."""
    fake_ble_device = BLEDevice("57:4C:42:80:71:BA", "TL100_71BA")
    unavailable_callback = None

    def mock_track_unavailable(hass: Any, cb: Any, address: str, connectable: bool) -> MagicMock:
        nonlocal unavailable_callback
        unavailable_callback = cb
        return MagicMock()

    with (
        patch.object(bluetooth, "async_ble_device_from_address", return_value=fake_ble_device),
        patch.object(bluetooth, "async_track_unavailable", side_effect=mock_track_unavailable),
    ):
        result = await async_setup_entry(mock_hass, mock_entry)
        assert result is True
        assert unavailable_callback is not None

        # Simulate device unavailable timeout
        mock_service_info = MagicMock()
        mock_hass.async_create_task = MagicMock()

        unavailable_callback(mock_service_info)
        mock_hass.async_create_task.assert_called_once()
