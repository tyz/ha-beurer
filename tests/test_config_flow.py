"""Unit tests for Beurer config flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
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
