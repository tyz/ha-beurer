"""Unit tests for Beurer config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from custom_components.beurer.config_flow import BeurerFlowHandler
from homeassistant.data_entry_flow import AbortFlow


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
