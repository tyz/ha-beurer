"""Tests for packet framing, checksums and module-level helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beurer.beurer import (
    BeurerInstance,
    create_status_callback,
    discover,
    get_device,
)


def test_checksum_calculation(beurer_instance: BeurerInstance) -> None:
    """Test XOR checksum calculation logic."""
    # Test simple XOR sequence
    payload = [0x31, 0x01, 50]
    initial_byte = len(payload) + 2
    expected = initial_byte ^ 0x31 ^ 0x01 ^ 50
    assert beurer_instance.makeChecksum(initial_byte, payload) == expected

@pytest.mark.asyncio
async def test_create_status_callback() -> None:
    """Test create_status_callback resolves future with received data."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[bytearray] = loop.create_future()
    callback = create_status_callback(future)

    data = bytearray([1, 2, 3])
    callback(1, data)

    assert future.done()
    assert future.result() == data

@pytest.mark.asyncio
async def test_discover_function() -> None:
    """Test discover finds and filters TL100 devices."""
    dev1 = MagicMock()
    dev1.name = "TL100 Lamp"
    dev1.address = "11:22:33:44:55:66"

    dev2 = MagicMock()
    dev2.name = "Other Device"
    dev2.address = "22:33:44:55:66:77"

    with patch("custom_components.beurer.beurer.BleakScanner.discover", AsyncMock(return_value=[dev1, dev2])):
        found = await discover()
        assert len(found) == 1
        assert found[0].name == "TL100 Lamp"

def test_find_effect_position(beurer_instance: BeurerInstance) -> None:
    """Test effect name to index mapping."""
    assert beurer_instance.find_effect_position("Off") == 0
    assert beurer_instance.find_effect_position("Rainbow") == 2
    assert beurer_instance.find_effect_position("NonExistentEffect") == 0

@pytest.mark.asyncio
async def test_get_device_function() -> None:
    """Test get_device finds device by mac address or returns None."""
    dev1 = MagicMock()
    dev1.address = "AA:BB:CC:DD:EE:FF"

    with patch("custom_components.beurer.beurer.BleakScanner.discover", AsyncMock(return_value=[dev1])):
        result = await get_device("aa:bb:cc:dd:ee:ff")
        assert result is dev1

        result_none = await get_device("00:11:22:33:44:55")
        assert result_none is None

