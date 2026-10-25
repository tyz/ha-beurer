"""Unit tests for BeurerTimerSwitch entity."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError
from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.const import DOMAIN
from custom_components.beurer.switch import BeurerTimerSwitch, async_setup_entry
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_instance() -> MagicMock:
    """Return a mock BeurerInstance."""
    instance = MagicMock(spec=BeurerInstance)
    instance.mac = "57:4C:42:80:71:BA"
    instance.is_on = True
    instance.timer_active = False
    instance.is_connected = True
    instance.firmware_version = "1.35"
    instance.enable_timer = AsyncMock()
    instance.disable_timer = AsyncMock()
    instance.register_update_callback = MagicMock(return_value=MagicMock())
    return instance


def test_switch_properties(mock_instance: MagicMock) -> None:
    """Test switch entity basic properties."""
    switch = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")
    assert switch.unique_id == "57:4C:42:80:71:BA_timer"
    assert switch.is_on is False
    assert switch.translation_key == "timer"
    assert switch.has_entity_name is True

    mock_instance.timer_active = True
    assert switch.is_on is True

    # Device info with firmware version
    assert switch.device_info["manufacturer"] == "Beurer"
    assert switch.device_info["model"] == "TL 100"
    assert switch.device_info["sw_version"] == "1.35"

    # Device info without firmware version
    mock_instance.firmware_version = None
    switch_no_fw = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")
    assert "sw_version" not in switch_no_fw.device_info


@pytest.mark.asyncio
async def test_switch_async_turn_on(mock_instance: MagicMock) -> None:
    """Test turning on switch enables timer."""
    switch = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")
    await switch.async_turn_on()
    mock_instance.enable_timer.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_async_turn_on_fails_when_lamp_off(mock_instance: MagicMock) -> None:
    """Test turning on switch raises HomeAssistantError when lamp is off."""
    mock_instance.is_on = False
    switch = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await switch.async_turn_on()

    assert exc_info.value.translation_key == "lamp_must_be_on"
    mock_instance.enable_timer.assert_not_called()


@pytest.mark.asyncio
async def test_switch_async_turn_off(mock_instance: MagicMock) -> None:
    """Test turning off switch disables timer."""
    switch = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")
    await switch.async_turn_off()
    mock_instance.disable_timer.assert_awaited_once()


@pytest.mark.asyncio
async def test_switch_turn_on_error_handling(mock_instance: MagicMock) -> None:
    """Test error handling when enabling timer fails."""
    mock_instance.enable_timer.side_effect = BleakError("Write failed")
    switch = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await switch.async_turn_on()
    assert exc_info.value.translation_key == "communication_error"


@pytest.mark.asyncio
async def test_switch_turn_off_error_handling(mock_instance: MagicMock) -> None:
    """Test error handling when disabling timer fails."""
    mock_instance.disable_timer.side_effect = TimeoutError("Timeout")
    switch = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await switch.async_turn_off()
    assert exc_info.value.translation_key == "communication_error"


@pytest.mark.asyncio
async def test_switch_lifecycle_callbacks(mock_instance: MagicMock) -> None:
    """Test registering and unregistering update callbacks."""
    mock_unregister = MagicMock()
    mock_instance.register_update_callback.return_value = mock_unregister

    switch = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")
    await switch.async_added_to_hass()
    mock_instance.register_update_callback.assert_called_once()

    await switch.async_will_remove_from_hass()
    mock_unregister.assert_called_once()


def test_switch_available(mock_instance: MagicMock) -> None:
    """Test switch availability depending on connection and advertisements."""
    switch = BeurerTimerSwitch(mock_instance, "TL100", "entry_123")

    # Connected
    mock_instance.is_connected = True
    assert switch.available is True

    # Disconnected but advertising
    mock_instance.is_connected = False
    mock_hass = MagicMock()
    switch.hass = mock_hass
    with patch.object(bluetooth, "async_ble_device_from_address", return_value=MagicMock()):
        assert switch.available is True

    # Disconnected and not advertising
    with patch.object(bluetooth, "async_ble_device_from_address", return_value=None):
        assert switch.available is False

    # Disconnected and hass is None fallback
    switch.hass = None
    assert switch.available is True


@pytest.mark.asyncio
async def test_async_setup_entry_switch(mock_instance: MagicMock) -> None:
    """Test async_setup_entry adds switch entity."""
    mock_hass = MagicMock()
    mock_hass.data = {DOMAIN: {"entry_123": mock_instance}}
    mock_entry = ConfigEntry(entry_id="entry_123", data={"name": "TL100"})
    mock_add_entities = MagicMock()

    await async_setup_entry(mock_hass, mock_entry, mock_add_entities)
    mock_add_entities.assert_called_once()
    entities = mock_add_entities.call_args[0][0]
    assert len(entities) == 1
    assert isinstance(entities[0], BeurerTimerSwitch)
