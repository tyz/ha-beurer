"""Unit tests for BeurerTimerDurationSelect entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError
from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.const import DEFAULT_TIMER_DURATION, DOMAIN, VALID_TIMER_DURATIONS
from custom_components.beurer.select import (
    BeurerTimerDurationSelect,
    async_setup_entry,
)
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_instance() -> MagicMock:
    """Return a mock BeurerInstance."""
    instance = MagicMock(spec=BeurerInstance)
    instance.mac = "57:4C:42:80:71:BA"
    instance.timer_duration = DEFAULT_TIMER_DURATION
    instance.is_connected = True
    instance.firmware_version = "1.35"
    instance.set_timer_duration = AsyncMock()
    instance.register_update_callback = MagicMock(return_value=MagicMock())
    return instance


def test_select_properties(mock_instance: MagicMock) -> None:
    """Test select entity basic properties and categories."""
    entity = BeurerTimerDurationSelect(mock_instance, "TL100", "entry_123")

    assert entity.has_entity_name is True
    assert entity.translation_key == "timer_duration"
    assert entity.entity_category == EntityCategory.CONFIG
    assert entity.options == [str(d) for d in VALID_TIMER_DURATIONS]
    assert entity.unique_id == "57:4C:42:80:71:BA_timer_duration"
    assert entity.current_option == str(DEFAULT_TIMER_DURATION)

    # Device info with firmware version
    assert entity.device_info["manufacturer"] == "Beurer"
    assert entity.device_info["model"] == "TL 100"
    assert entity.device_info["sw_version"] == "1.35"

    # Device info without firmware version
    mock_instance.firmware_version = None
    entity_no_fw = BeurerTimerDurationSelect(mock_instance, "TL100", "entry_123")
    assert "sw_version" not in entity_no_fw.device_info


@pytest.mark.asyncio
async def test_select_async_select_option(mock_instance: MagicMock) -> None:
    """Test selecting a valid timer duration option."""
    entity = BeurerTimerDurationSelect(mock_instance, "TL100", "entry_123")

    await entity.async_select_option("45")
    mock_instance.set_timer_duration.assert_awaited_once_with(45)


@pytest.mark.asyncio
async def test_select_async_select_option_error_handling(
    mock_instance: MagicMock,
) -> None:
    """Test error handling when BLE fails during select_option."""
    entity = BeurerTimerDurationSelect(mock_instance, "TL100", "entry_123")
    mock_instance.set_timer_duration.side_effect = BleakError("Connection failed")

    with pytest.raises(HomeAssistantError) as exc_info:
        await entity.async_select_option("30")

    assert exc_info.value.translation_key == "communication_error"


@pytest.mark.asyncio
async def test_select_lifecycle_callbacks(mock_instance: MagicMock) -> None:
    """Test callback registration and cleanup."""
    mock_unregister = MagicMock()
    mock_instance.register_update_callback.return_value = mock_unregister

    entity = BeurerTimerDurationSelect(mock_instance, "TL100", "entry_123")
    await entity.async_added_to_hass()
    mock_instance.register_update_callback.assert_called_once()

    await entity.async_will_remove_from_hass()
    mock_unregister.assert_called_once()


def test_select_available(mock_instance: MagicMock) -> None:
    """Test select availability depending on connection and advertisements."""
    entity = BeurerTimerDurationSelect(mock_instance, "TL100", "entry_123")

    # Connected
    mock_instance.is_connected = True
    assert entity.available is True

    # Disconnected and advertising
    mock_instance.is_connected = False
    entity.hass = MagicMock()
    with patch.object(bluetooth, "async_ble_device_from_address", return_value=MagicMock()):
        assert entity.available is True

    # Disconnected and not advertising
    with patch.object(bluetooth, "async_ble_device_from_address", return_value=None):
        assert entity.available is False

    # Disconnected and hass is None fallback
    entity.hass = None
    assert entity.available is True


@pytest.mark.asyncio
async def test_async_setup_entry_select(mock_instance: MagicMock) -> None:
    """Test async_setup_entry adds select entity."""
    mock_hass = MagicMock()
    mock_hass.data = {DOMAIN: {"entry_123": mock_instance}}
    mock_entry = ConfigEntry(entry_id="entry_123", data={"name": "TL100"})
    mock_add_entities = MagicMock()

    await async_setup_entry(mock_hass, mock_entry, mock_add_entities)
    mock_add_entities.assert_called_once()
    entities = mock_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert isinstance(entities[0], BeurerTimerDurationSelect)
