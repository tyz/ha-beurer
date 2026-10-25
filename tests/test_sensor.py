"""Unit tests for BeurerTimerRemainingSensor entity."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.const import DOMAIN
from custom_components.beurer.sensor import (
    BeurerTimerRemainingSensor,
    async_setup_entry,
)
from homeassistant.components import bluetooth
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime


@pytest.fixture
def mock_instance() -> MagicMock:
    """Return a mock BeurerInstance."""
    instance = MagicMock(spec=BeurerInstance)
    instance.mac = "57:4C:42:80:71:BA"
    instance.timer_minutes_remaining = 10
    instance.is_connected = True
    instance.firmware_version = "1.35"
    instance.register_update_callback = MagicMock(return_value=MagicMock())
    return instance


def test_sensor_properties(mock_instance: MagicMock) -> None:
    """Test sensor entity basic properties."""
    sensor = BeurerTimerRemainingSensor(mock_instance, "TL100", "entry_123")
    assert sensor.unique_id == "57:4C:42:80:71:BA_timer_remaining"
    assert sensor.native_value == 10
    assert sensor.native_unit_of_measurement == UnitOfTime.MINUTES
    assert sensor.device_class == SensorDeviceClass.DURATION
    assert sensor.state_class == SensorStateClass.MEASUREMENT
    assert sensor.translation_key == "timer_remaining"
    assert sensor.has_entity_name is True

    # Device info with firmware version
    assert sensor.device_info["manufacturer"] == "Beurer"
    assert sensor.device_info["model"] == "TL 100"
    assert sensor.device_info["sw_version"] == "1.35"

    # Device info without firmware version
    mock_instance.firmware_version = None
    sensor_no_fw = BeurerTimerRemainingSensor(mock_instance, "TL100", "entry_123")
    assert "sw_version" not in sensor_no_fw.device_info


@pytest.mark.asyncio
async def test_sensor_lifecycle_callbacks(mock_instance: MagicMock) -> None:
    """Test registering and unregistering update callbacks."""
    mock_unregister = MagicMock()
    mock_instance.register_update_callback.return_value = mock_unregister

    sensor = BeurerTimerRemainingSensor(mock_instance, "TL100", "entry_123")
    await sensor.async_added_to_hass()
    mock_instance.register_update_callback.assert_called_once()

    await sensor.async_will_remove_from_hass()
    mock_unregister.assert_called_once()


def test_sensor_available(mock_instance: MagicMock) -> None:
    """Test sensor availability depending on connection and advertisements."""
    sensor = BeurerTimerRemainingSensor(mock_instance, "TL100", "entry_123")

    # Connected
    mock_instance.is_connected = True
    assert sensor.available is True

    # Disconnected but advertising
    mock_instance.is_connected = False
    mock_hass = MagicMock()
    sensor.hass = mock_hass
    with patch.object(bluetooth, "async_ble_device_from_address", return_value=MagicMock()):
        assert sensor.available is True

    # Disconnected and not advertising
    with patch.object(bluetooth, "async_ble_device_from_address", return_value=None):
        assert sensor.available is False

    # Disconnected and hass is None fallback
    sensor.hass = None
    assert sensor.available is True


@pytest.mark.asyncio
async def test_async_setup_entry_sensor(mock_instance: MagicMock) -> None:
    """Test async_setup_entry adds sensor entity."""
    mock_hass = MagicMock()
    mock_hass.data = {DOMAIN: {"entry_123": mock_instance}}
    mock_entry = ConfigEntry(entry_id="entry_123", data={"name": "TL100"})
    mock_add_entities = MagicMock()

    await async_setup_entry(mock_hass, mock_entry, mock_add_entities)
    mock_add_entities.assert_called_once()
    entities = mock_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert isinstance(entities[0], BeurerTimerRemainingSensor)
