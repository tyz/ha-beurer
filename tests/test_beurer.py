"""Unit tests for Beurer communication instance."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from bleak import BLEDevice
from custom_components.beurer.beurer import BeurerInstance
from homeassistant.components.light import ColorMode


@pytest.fixture
def mock_device() -> BLEDevice:
    """Return a mock BLEDevice."""
    return BLEDevice("57:4C:42:80:71:BA", "TL100_71BA")


@pytest.fixture
def beurer_instance(mock_device: BLEDevice) -> BeurerInstance:
    """Return an initialized BeurerInstance with mocked _write."""
    instance = BeurerInstance(mock_device)
    instance._write = AsyncMock()
    instance._device = MagicMock()
    instance._device.is_connected = True
    return instance


def test_checksum_calculation(beurer_instance: BeurerInstance) -> None:
    """Test XOR checksum calculation logic."""
    # Test simple XOR sequence
    payload = [0x31, 0x01, 50]
    initial_byte = len(payload) + 2
    expected = initial_byte ^ 0x31 ^ 0x01 ^ 50
    assert beurer_instance.makeChecksum(initial_byte, payload) == expected


def test_find_effect_position(beurer_instance: BeurerInstance) -> None:
    """Test effect name to index mapping."""
    assert beurer_instance.find_effect_position("Off") == 0
    assert beurer_instance.find_effect_position("Rainbow") == 2
    assert beurer_instance.find_effect_position("NonExistentEffect") == 0


@pytest.mark.asyncio
async def test_set_white_caps_at_99_percent(beurer_instance: BeurerInstance) -> None:
    """Test that 100% white brightness (255) is capped at 99% to prevent red shift."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance.triggerStatus = AsyncMock()
    beurer_instance._light_on = True

    # Full brightness 255 (100%) -> must be capped at 99% (0x63)
    await beurer_instance.set_white(255)

    assert len(sent_packets) == 1
    packet = list(sent_packets[0])
    command_type = packet[7]
    mode_byte = packet[8]
    intensity_byte = packet[9]

    assert command_type == 0x31
    assert mode_byte == 0x01
    assert intensity_byte == 99  # NOT 100!
    assert beurer_instance.color_mode == ColorMode.WHITE


@pytest.mark.asyncio
async def test_set_white_lower_percentages(beurer_instance: BeurerInstance) -> None:
    """Test that white brightness below 100% scales linearly."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance.triggerStatus = AsyncMock()
    beurer_instance._light_on = True

    # Half brightness ~128 -> ~50%
    await beurer_instance.set_white(128)
    packet = list(sent_packets[0])
    assert packet[9] == 50


@pytest.mark.asyncio
async def test_set_color(beurer_instance: BeurerInstance) -> None:
    """Test setting RGB color sends packet with correct RGB bytes."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance.triggerStatus = AsyncMock()
    beurer_instance._color_on = True

    await beurer_instance.set_color((12, 34, 56))

    packet = list(sent_packets[0])
    assert packet[7] == 0x32
    assert packet[8] == 12
    assert packet[9] == 34
    assert packet[10] == 56
    assert beurer_instance.color_mode == ColorMode.RGB
    assert beurer_instance.rgb_color == (12, 34, 56)


@pytest.mark.asyncio
async def test_set_color_brightness(beurer_instance: BeurerInstance) -> None:
    """Test setting color brightness sends packet with mode 0x02."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance.triggerStatus = AsyncMock()
    beurer_instance._color_on = True

    await beurer_instance.set_color_brightness(255)

    packet = list(sent_packets[0])
    assert packet[7] == 0x31
    assert packet[8] == 0x02
    assert packet[9] == 100
    assert beurer_instance.color_mode == ColorMode.RGB


@pytest.mark.asyncio
async def test_notification_handler_reply_version_1(beurer_instance: BeurerInstance) -> None:
    """Test handling status reply version 1 (white daylight state)."""
    callback_called = False

    def update_callback() -> None:
        nonlocal callback_called
        callback_called = True

    beurer_instance.set_update_callback(update_callback)

    # res: [..., ..., ..., ..., ..., ..., ..., ..., reply_version=1, is_on=1, brightness=50]
    payload = bytearray([0] * 8 + [1, 1, 50])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance.color_mode == ColorMode.WHITE
    # 50% of 255 is 127
    assert beurer_instance.white_brightness == int(50 * 255 / 100)
    assert callback_called is True


@pytest.mark.asyncio
async def test_notification_handler_reply_version_2(beurer_instance: BeurerInstance) -> None:
    """Test handling status reply version 2 (RGB color state)."""
    callback_called = False

    def update_callback() -> None:
        nonlocal callback_called
        callback_called = True

    beurer_instance.set_update_callback(update_callback)

    # reply_version=2, color_on=1, brightness=80, _, _, r=10, g=20, b=30, effect=2 (Rainbow)
    payload = bytearray([0] * 8 + [2, 1, 80, 0, 0, 10, 20, 30, 2])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance.color_mode == ColorMode.RGB
    assert beurer_instance.rgb_color == (10, 20, 30)
    assert beurer_instance.effect == "Rainbow"
    assert beurer_instance.color_brightness == int(80 * 255 / 100)
    assert callback_called is True


@pytest.mark.asyncio
async def test_notification_handler_reply_version_255_off(beurer_instance: BeurerInstance) -> None:
    """Test handling status reply version 255 (device turns off)."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = True

    payload = bytearray([0] * 8 + [255])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_handler_reply_version_0_shutdown(beurer_instance: BeurerInstance) -> None:
    """Test handling status reply version 0 (device shutdown notification)."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = True

    payload = bytearray([0] * 8 + [0])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_handler_short_packet(beurer_instance: BeurerInstance) -> None:
    """Test handling malformed short packets without raising exceptions."""
    char = MagicMock()
    await beurer_instance.notification_handler(char, bytearray([0, 1, 2]))
    # Should safely return without crash


@pytest.mark.asyncio
async def test_turn_on_defaults_to_white_mode(beurer_instance: BeurerInstance) -> None:
    """Test that turn_on defaults to white daylight channel."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance.triggerStatus = AsyncMock()

    await beurer_instance.turn_on()

    assert len(sent_packets) == 1
    packet = list(sent_packets[0])
    assert packet[7] == 0x37
    assert packet[8] == 0x01
    assert beurer_instance.color_mode == ColorMode.WHITE


@pytest.mark.asyncio
async def test_set_white_turns_off_active_color_channel(beurer_instance: BeurerInstance) -> None:
    """Test that switching to white turns off active color channel."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance.triggerStatus = AsyncMock()
    beurer_instance._color_on = True
    beurer_instance._light_on = True

    await beurer_instance.set_white(150)

    # First packet: turn off color [0x35, 0x02]
    # Second packet: set white intensity [0x31, 0x01, ...]
    assert len(sent_packets) == 2
    pkt1 = list(sent_packets[0])
    assert pkt1[7] == 0x35
    assert pkt1[8] == 0x02
    assert beurer_instance.color_mode == ColorMode.WHITE


@pytest.mark.asyncio
async def test_set_color_turns_off_active_white_channel(beurer_instance: BeurerInstance) -> None:
    """Test that switching to color turns off active white channel."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance.triggerStatus = AsyncMock()
    beurer_instance._light_on = True
    beurer_instance._color_on = True

    await beurer_instance.set_color((255, 128, 0))

    # First packet: turn off white [0x35, 0x01]
    # Second packet: set color [0x32, 255, 128, 0]
    assert len(sent_packets) == 2
    pkt1 = list(sent_packets[0])
    assert pkt1[7] == 0x35
    assert pkt1[8] == 0x01
    assert beurer_instance.color_mode == ColorMode.RGB
