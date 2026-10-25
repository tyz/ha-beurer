"""Unit tests for Beurer config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.data_entry_flow import AbortFlow

from custom_components.beurer.config_flow import BeurerFlowHandler


@pytest.mark.asyncio
async def test_flow_user_step_redirects_to_manual_when_selected() -> None:
    """Test selecting manual MAC entry redirects to step_manual."""
    flow = BeurerFlowHandler()
    result = await flow.async_step_user({"mac": "manual", "name": "Custom Lamp"})
    assert result["type"] == "form"
    assert result["step_id"] == "manual"


@pytest.mark.asyncio
async def test_flow_manual_step_submits_to_validate() -> None:
    """Test submitting manual MAC moves to validate step."""
    flow = BeurerFlowHandler()
    with patch.object(flow, "toggle_light", AsyncMock(return_value=None)):
        result = await flow.async_step_manual({"mac": "AA:BB:CC:DD:EE:FF", "name": "Test Lamp"})
        assert flow.mac == "AA:BB:CC:DD:EE:FF"
        assert flow.name == "Test Lamp"
        assert result["type"] == "form"
        assert result["step_id"] == "validate"


@pytest.mark.asyncio
async def test_flow_validate_step_success_creates_entry() -> None:
    """Test user confirming light flickered creates entry."""
    flow = BeurerFlowHandler()
    flow.mac = "AA:BB:CC:DD:EE:FF"
    flow.name = "My TL100"

    result = await flow.async_step_validate({"flicker": True})
    assert result["type"] == "create_entry"
    assert result["title"] == "My TL100"
    assert result["data"]["mac"] == "AA:BB:CC:DD:EE:FF"


@pytest.mark.asyncio
async def test_flow_toggle_light_fails_when_device_not_found() -> None:
    """Test toggle_light returns error when device cannot be found."""
    flow = BeurerFlowHandler()
    flow.mac = "AA:BB:CC:DD:EE:FF"

    with patch("custom_components.beurer.config_flow.get_device", AsyncMock(return_value=None)):
        error = await flow.toggle_light()
        assert error is not None
        assert "Was not able to find device" in str(error)


@pytest.mark.asyncio
async def test_flow_bluetooth_step_shows_confirm_form() -> None:
    """Test Bluetooth discovery step shows confirmation form."""
    mock_discovery = MagicMock()
    mock_discovery.address = "AA:BB:CC:DD:EE:FF"
    mock_discovery.name = "TL100_EEFF"

    flow = BeurerFlowHandler()
    result = await flow.async_step_bluetooth(mock_discovery)

    assert result["type"] == "form"
    assert result["step_id"] == "bluetooth_confirm"
    assert flow.mac == "AA:BB:CC:DD:EE:FF"
    assert flow.name == "TL100_EEFF"
    assert flow.context["title_placeholders"] == {"name": "TL100_EEFF"}


@pytest.mark.asyncio
async def test_flow_bluetooth_step_aborts_if_already_configured() -> None:
    """Test Bluetooth discovery step aborts if device unique ID is already configured."""
    mock_discovery = MagicMock()
    mock_discovery.address = "AA:BB:CC:DD:EE:FF"
    mock_discovery.name = "TL100_EEFF"

    flow = BeurerFlowHandler()
    with patch.object(flow, "_async_current_ids", return_value={"aabbccddeeff"}):
        with pytest.raises(AbortFlow) as exc_info:
            await flow.async_step_bluetooth(mock_discovery)
        assert exc_info.value.reason == "already_configured"


@pytest.mark.asyncio
async def test_flow_bluetooth_confirm_submits_to_validate() -> None:
    """Test submitting confirmation moves to validate step."""
    flow = BeurerFlowHandler()
    flow.mac = "AA:BB:CC:DD:EE:FF"
    flow.name = "TL100_EEFF"

    with patch.object(flow, "toggle_light", AsyncMock(return_value=None)):
        result = await flow.async_step_bluetooth_confirm({})
        assert result["type"] == "form"
        assert result["step_id"] == "validate"


@pytest.mark.asyncio
async def test_flow_user_step_with_discovered_devices() -> None:
    """Test user step shows discovery form when devices found."""
    mock_dev = MagicMock()
    mock_dev.address = "AA:BB:CC:DD:EE:FF"
    mock_dev.name = "TL100 Lamp"

    flow = BeurerFlowHandler()
    with patch(
        "custom_components.beurer.config_flow.discover",
        AsyncMock(return_value=[mock_dev]),
    ):
        result = await flow.async_step_user(None)
        assert result["type"] == "form"
        assert result["step_id"] == "user"


@pytest.mark.asyncio
async def test_flow_user_step_no_devices_redirects_to_manual() -> None:
    """Test user step redirects to manual when no devices found."""
    flow = BeurerFlowHandler()
    with patch("custom_components.beurer.config_flow.discover", AsyncMock(return_value=[])):
        result = await flow.async_step_user(None)
        assert result["type"] == "form"
        assert result["step_id"] == "manual"


@pytest.mark.asyncio
async def test_flow_user_step_submits_selected_device() -> None:
    """Test submitting selected device in user step proceeds to validate."""
    flow = BeurerFlowHandler()
    with patch.object(flow, "toggle_light", AsyncMock(return_value=None)):
        result = await flow.async_step_user({"mac": "AA:BB:CC:DD:EE:FF", "name": "Living Room"})
        assert flow.mac == "AA:BB:CC:DD:EE:FF"
        assert flow.name == "Living Room"
        assert result["type"] == "form"
        assert result["step_id"] == "validate"


@pytest.mark.asyncio
async def test_flow_user_step_aborts_if_already_configured() -> None:
    """Test submitting already configured device in user step aborts."""
    flow = BeurerFlowHandler()
    with patch.object(flow, "_async_current_ids", return_value={"aabbccddeeff"}):
        with pytest.raises(AbortFlow) as exc_info:
            await flow.async_step_user({"mac": "AA:BB:CC:DD:EE:FF", "name": "Duplicate"})
        assert exc_info.value.reason == "already_configured"


@pytest.mark.asyncio
async def test_flow_manual_step_aborts_if_already_configured() -> None:
    """Test submitting already configured device in manual step aborts."""
    flow = BeurerFlowHandler()
    with patch.object(flow, "_async_current_ids", return_value={"aabbccddeeff"}):
        with pytest.raises(AbortFlow) as exc_info:
            await flow.async_step_manual({"mac": "AA:BB:CC:DD:EE:FF", "name": "Duplicate"})
        assert exc_info.value.reason == "already_configured"


@pytest.mark.asyncio
async def test_flow_validate_flicker_false_aborts() -> None:
    """Test user answering flicker=False aborts with cannot_validate."""
    flow = BeurerFlowHandler()
    result = await flow.async_step_validate({"flicker": False})
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_validate"


@pytest.mark.asyncio
async def test_flow_validate_retry_false_aborts() -> None:
    """Test user declining retry aborts with cannot_connect."""
    flow = BeurerFlowHandler()
    result = await flow.async_step_validate({"retry": False})
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


@pytest.mark.asyncio
async def test_flow_validate_toggle_error_shows_retry_form() -> None:
    """Test error during toggle_light shows validate retry form."""
    flow = BeurerFlowHandler()
    with patch.object(flow, "toggle_light", AsyncMock(return_value=Exception("Connection timed out"))):
        result = await flow.async_step_validate(None)
        assert result["type"] == "form"
        assert result["step_id"] == "validate"
        assert result["errors"] == {"base": "connect"}


@pytest.mark.asyncio
async def test_flow_toggle_light_no_mac_returns_error() -> None:
    """Test toggle_light returns Exception when mac is not set."""
    flow = BeurerFlowHandler()
    flow.mac = None
    error = await flow.toggle_light()
    assert error is not None
    assert "No MAC address specified" in str(error)


@pytest.mark.asyncio
async def test_flow_toggle_light_uses_hass_bluetooth() -> None:
    """Test toggle_light retrieves device from Home Assistant bluetooth component."""
    mock_device = MagicMock()
    mock_instance = MagicMock()
    mock_instance.is_on = True
    mock_instance.update = AsyncMock()
    mock_instance.turn_off = AsyncMock()
    mock_instance.turn_on = AsyncMock()
    mock_instance.disconnect = AsyncMock()

    flow = BeurerFlowHandler()
    flow.hass = MagicMock()
    flow.mac = "AA:BB:CC:DD:EE:FF"

    with (
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            return_value=mock_device,
        ),
        patch(
            "custom_components.beurer.config_flow.BeurerInstance",
            return_value=mock_instance,
        ),
        patch("asyncio.sleep", AsyncMock()),
    ):
        error = await flow.toggle_light()
        assert error is None
        mock_instance.turn_off.assert_awaited_once()
        mock_instance.turn_on.assert_awaited_once()
        mock_instance.disconnect.assert_awaited_once_with(closing=True)


@pytest.mark.asyncio
async def test_flow_toggle_light_when_light_initially_off() -> None:
    """Test toggle_light turns light on then off when initially off."""
    mock_device = MagicMock()
    mock_instance = MagicMock()
    mock_instance.is_on = False
    mock_instance.update = AsyncMock()
    mock_instance.turn_on = AsyncMock()
    mock_instance.turn_off = AsyncMock()
    mock_instance.disconnect = AsyncMock()

    flow = BeurerFlowHandler()
    flow.mac = "AA:BB:CC:DD:EE:FF"

    with (
        patch(
            "custom_components.beurer.config_flow.get_device",
            AsyncMock(return_value=mock_device),
        ),
        patch(
            "custom_components.beurer.config_flow.BeurerInstance",
            return_value=mock_instance,
        ),
        patch("asyncio.sleep", AsyncMock()),
    ):
        error = await flow.toggle_light()
        assert error is None
        mock_instance.turn_on.assert_awaited_once()
        mock_instance.turn_off.assert_awaited_once()
        mock_instance.disconnect.assert_awaited_once_with(closing=True)


@pytest.mark.asyncio
async def test_flow_toggle_light_catches_exception() -> None:
    """Test toggle_light catches exception during update or toggle and disconnects."""
    mock_device = MagicMock()
    mock_instance = MagicMock()
    mock_instance.update = AsyncMock(side_effect=RuntimeError("BLE crash"))
    mock_instance.disconnect = AsyncMock()

    flow = BeurerFlowHandler()
    flow.mac = "AA:BB:CC:DD:EE:FF"

    with (
        patch(
            "custom_components.beurer.config_flow.get_device",
            AsyncMock(return_value=mock_device),
        ),
        patch(
            "custom_components.beurer.config_flow.BeurerInstance",
            return_value=mock_instance,
        ),
    ):
        error = await flow.toggle_light()
        assert isinstance(error, RuntimeError)
        mock_instance.disconnect.assert_awaited_once_with(closing=True)


@pytest.mark.asyncio
async def test_flow_toggle_light_bluetooth_attribute_error_falls_back() -> None:
    """Test toggle_light falls back to get_device when bluetooth raises AttributeError."""
    mock_device = MagicMock()
    mock_instance = MagicMock()
    mock_instance.is_on = True
    mock_instance.update = AsyncMock()
    mock_instance.turn_off = AsyncMock()
    mock_instance.turn_on = AsyncMock()
    mock_instance.disconnect = AsyncMock()

    flow = BeurerFlowHandler()
    flow.hass = MagicMock()
    flow.mac = "AA:BB:CC:DD:EE:FF"

    with (
        patch(
            "homeassistant.components.bluetooth.async_ble_device_from_address",
            side_effect=AttributeError("no attribute"),
        ),
        patch(
            "custom_components.beurer.config_flow.get_device",
            AsyncMock(return_value=mock_device),
        ),
        patch(
            "custom_components.beurer.config_flow.BeurerInstance",
            return_value=mock_instance,
        ),
        patch("asyncio.sleep", AsyncMock()),
    ):
        error = await flow.toggle_light()
        assert error is None


@pytest.mark.asyncio
async def test_flow_toggle_light_reuses_existing_instance() -> None:
    """Test toggle_light updates device on existing BeurerInstance."""
    mock_device = MagicMock()
    mock_instance = MagicMock()
    mock_instance.is_on = False
    mock_instance.update = AsyncMock()
    mock_instance.turn_on = AsyncMock()
    mock_instance.turn_off = AsyncMock()
    mock_instance.disconnect = AsyncMock()

    flow = BeurerFlowHandler()
    flow.mac = "AA:BB:CC:DD:EE:FF"
    flow.beurer_instance = mock_instance

    with (
        patch(
            "custom_components.beurer.config_flow.get_device",
            AsyncMock(return_value=mock_device),
        ),
        patch("asyncio.sleep", AsyncMock()),
    ):
        error = await flow.toggle_light()
        assert error is None
        mock_instance.set_device.assert_called_once_with(mock_device)


def _make_reauth_flow(flow: BeurerFlowHandler) -> BeurerFlowHandler:
    """Attach a reauth entry to the flow, mirroring what Home Assistant does."""
    flow._set_reauth_entry(
        ConfigEntry(
            entry_id="reauth_entry",
            data={CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Old Lamp"},
        )
    )
    return flow


@pytest.mark.asyncio
async def test_flow_reauth_starts_with_confirm_form_prefilled() -> None:
    """Test reauth shows a prefilled form with the currently stored address."""
    flow = _make_reauth_flow(BeurerFlowHandler())

    result = await flow.async_step_reauth({CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Old Lamp"})

    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert flow.mac == "AA:BB:CC:DD:EE:FF"
    assert flow.name == "Old Lamp"
    assert flow.context["title_placeholders"] == {"name": "Old Lamp"}


@pytest.mark.asyncio
async def test_flow_reauth_confirm_moves_to_validate() -> None:
    """Test submitting corrected credentials advances to the blink validation."""
    flow = _make_reauth_flow(BeurerFlowHandler())
    await flow.async_step_reauth({CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Old Lamp"})

    with patch.object(flow, "toggle_light", AsyncMock(return_value=None)):
        result = await flow.async_step_reauth_confirm({CONF_MAC: "11:22:33:44:55:66", "name": "New Lamp"})

    assert flow.mac == "11:22:33:44:55:66"
    assert flow.name == "New Lamp"
    assert result["type"] == "form"
    assert result["step_id"] == "validate"


@pytest.mark.asyncio
async def test_flow_reauth_success_updates_existing_entry() -> None:
    """Test a confirmed blink during reauth updates the entry instead of creating one."""
    flow = _make_reauth_flow(BeurerFlowHandler())
    await flow.async_step_reauth({CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Old Lamp"})
    await flow.async_step_reauth_confirm({CONF_MAC: "11:22:33:44:55:66", "name": "New Lamp"})

    result = await flow.async_step_validate({"flicker": True})

    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert result["data_updates"] == {CONF_MAC: "11:22:33:44:55:66", "name": "New Lamp"}


@pytest.mark.asyncio
async def test_flow_reauth_keeps_existing_title() -> None:
    """Test reauth does not rename the entry, even though the name is editable."""
    flow = _make_reauth_flow(BeurerFlowHandler())
    await flow.async_step_reauth({CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Old Lamp"})
    await flow.async_step_reauth_confirm({CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Renamed By Accident"})

    assert flow._current_title() == flow._get_reauth_entry().title


@pytest.mark.asyncio
async def test_flow_reconfigure_shows_prefilled_form() -> None:
    """Test reconfigure shows the current address and name."""
    flow = BeurerFlowHandler()
    flow._set_reconfigure_entry(
        ConfigEntry(
            entry_id="existing",
            data={CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Desk Lamp"},
            unique_id="aabbccddeeff",
        )
    )

    result = await flow.async_step_reconfigure(None)

    assert result["type"] == "form"
    assert result["step_id"] == "reconfigure"
    assert flow.mac == "AA:BB:CC:DD:EE:FF"
    assert flow.name == "Desk Lamp"


@pytest.mark.asyncio
async def test_flow_reconfigure_success_updates_entry_and_title() -> None:
    """Test a confirmed reconfigure updates the stored data and the entry title."""
    entry = ConfigEntry(
        entry_id="existing",
        data={CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Desk Lamp"},
        unique_id="aabbccddeeff",
    )
    flow = BeurerFlowHandler()
    flow._set_reconfigure_entry(entry)
    await flow.async_step_reconfigure(None)

    with patch.object(flow, "toggle_light", AsyncMock(return_value=None)):
        result = await flow.async_step_reconfigure({CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Bedroom Lamp"})

    assert result["step_id"] == "validate"

    result = await flow.async_step_validate({"flicker": True})
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert result["title"] == "Bedroom Lamp"
    assert result["data_updates"] == {
        CONF_MAC: "AA:BB:CC:DD:EE:FF",
        "name": "Bedroom Lamp",
    }


@pytest.mark.asyncio
async def test_flow_reconfigure_aborts_for_different_lamp() -> None:
    """Test changing the MAC address to another lamp is rejected."""
    entry = ConfigEntry(
        entry_id="existing",
        data={CONF_MAC: "AA:BB:CC:DD:EE:FF", "name": "Desk Lamp"},
        unique_id="aabbccddeeff",
    )
    flow = BeurerFlowHandler()
    flow._set_reconfigure_entry(entry)
    await flow.async_step_reconfigure(None)

    with pytest.raises(AbortFlow) as exc_info:
        await flow.async_step_reconfigure({CONF_MAC: "11:22:33:44:55:66", "name": "Desk Lamp"})

    assert exc_info.value.reason == "wrong_device"


@pytest.mark.asyncio
async def test_flow_reconfigure_validate_failure_aborts() -> None:
    """Test declining the retry during reconfigure aborts without touching the entry."""
    flow = BeurerFlowHandler()
    flow._set_reconfigure_entry(
        ConfigEntry(
            entry_id="existing",
            data={CONF_MAC: "AA:BB:CC:DD:EE:FF"},
            unique_id="aabbccddeeff",
        )
    )
    await flow.async_step_reconfigure(None)

    result = await flow.async_step_validate({"retry": False})
    assert result["type"] == "abort"
    assert result["reason"] == "cannot_connect"


@pytest.mark.asyncio
async def test_flow_initial_validate_still_creates_entry() -> None:
    """Test the shared validate step still creates a new entry during setup."""
    flow = BeurerFlowHandler()
    flow.mac = "AA:BB:CC:DD:EE:FF"
    flow.name = None

    result = await flow.async_step_validate({"flicker": True})

    assert result["type"] == "create_entry"
    assert result["title"] == "Beurer TL 100"
