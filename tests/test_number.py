"""Unit tests for BeurerTimerDurationNumber entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.exceptions import HomeAssistantError

from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.number import BeurerTimerDurationNumber, async_setup_entry


@pytest.fixture
def mock_instance() -> MagicMock:
    """Return a mock BeurerInstance."""
    instance = MagicMock(spec=BeurerInstance)
    # Mirror the real BeurerInstance property: a lamp is only available while
    # an active BLE connection exists.
    type(instance).available = property(lambda self: bool(self.is_connected))
    instance.mac = "57:4C:42:80:71:BA"
    instance.timer_duration = 15
    instance.is_connected = True
    instance.firmware_version = "1.35"
    instance.set_timer_duration = AsyncMock()
    instance.register_update_callback = MagicMock(return_value=MagicMock())
    return instance


def test_number_properties(mock_instance: MagicMock) -> None:
    """Test number entity basic properties."""
    number = BeurerTimerDurationNumber(mock_instance, "TL100", "entry_123")
    assert number.unique_id == "57:4C:42:80:71:BA_timer_duration"
    assert number.native_value == 15.0
    assert number.native_min_value == 1.0
    assert number.native_max_value == 120.0
    assert number.native_step == 1.0
    assert number.native_unit_of_measurement == UnitOfTime.MINUTES
    assert number.translation_key == "timer_duration"
    assert number.has_entity_name is True
    assert number.entity_category == EntityCategory.CONFIG

    # Device info with firmware version
    assert number.device_info["manufacturer"] == "Beurer"
    assert number.device_info["model"] == "TL 100"
    assert number.device_info["sw_version"] == "1.35"

    # Device info without firmware version
    mock_instance.firmware_version = None
    number_no_fw = BeurerTimerDurationNumber(mock_instance, "TL100", "entry_123")
    assert "sw_version" not in number_no_fw.device_info


@pytest.mark.asyncio
async def test_number_async_set_native_value(mock_instance: MagicMock) -> None:
    """Test setting duration calls instance.set_timer_duration."""
    number = BeurerTimerDurationNumber(mock_instance, "TL100", "entry_123")
    await number.async_set_native_value(7.0)
    mock_instance.set_timer_duration.assert_awaited_once_with(7)


@pytest.mark.asyncio
async def test_number_async_set_native_value_error_handling(
    mock_instance: MagicMock,
) -> None:
    """Test exceptions are translated to HomeAssistantError."""
    mock_instance.set_timer_duration.side_effect = BleakError("Connection lost")
    number = BeurerTimerDurationNumber(mock_instance, "TL100", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await number.async_set_native_value(30.0)
    assert exc_info.value.translation_key == "communication_error"


@pytest.mark.asyncio
async def test_number_lifecycle_callbacks(mock_instance: MagicMock) -> None:
    """Test registering and unregistering update callbacks."""
    mock_unregister = MagicMock()
    mock_instance.register_update_callback.return_value = mock_unregister

    number = BeurerTimerDurationNumber(mock_instance, "TL100", "entry_123")
    await number.async_added_to_hass()
    mock_instance.register_update_callback.assert_called_once()

    await number.async_will_remove_from_hass()
    mock_unregister.assert_called_once()


def test_number_available(mock_instance: MagicMock) -> None:
    """Test number availability tracks the live BLE connection only.

    A lamp that is merely advertising but not connected cannot be controlled,
    so it must be reported as unavailable.
    """
    number = BeurerTimerDurationNumber(mock_instance, "TL100", "entry_123")

    # Connected: controllable.
    mock_instance.is_connected = True
    assert number.available is True

    # Disconnected but still advertising: not controllable, so unavailable.
    mock_instance.is_connected = False
    number.hass = MagicMock()
    with patch.object(bluetooth, "async_ble_device_from_address", return_value=MagicMock()):
        assert number.available is False


@pytest.mark.asyncio
async def test_async_setup_entry_number(mock_instance: MagicMock) -> None:
    """Test async_setup_entry adds number entity."""
    mock_hass = MagicMock()
    mock_entry = ConfigEntry(entry_id="entry_123", data={"name": "TL100"})
    mock_entry.runtime_data = mock_instance
    mock_add_entities = MagicMock()

    await async_setup_entry(mock_hass, mock_entry, mock_add_entities)
    mock_add_entities.assert_called_once()
    entities = mock_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert isinstance(entities[0], BeurerTimerDurationNumber)


def test_number_does_not_poll(mock_instance: MagicMock) -> None:
    """Test the push-only number entity is not polled by Home Assistant."""
    number = BeurerTimerDurationNumber(mock_instance, "TL100", "entry_123")

    assert number.should_poll is False
