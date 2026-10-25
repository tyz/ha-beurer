"""Tests for outgoing commands: brightness, colour, effects and timers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.light import ColorMode

from custom_components.beurer.beurer import BeurerInstance


@pytest.mark.asyncio
async def test_enable_and_disable_timer(beurer_instance: BeurerInstance) -> None:
    """Test starting and canceling hardware countdown timer."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._mode = ColorMode.WHITE
    beurer_instance._color_on = False
    beurer_instance._timer_duration = 30

    # Calling enable_timer when lamp is off raises RuntimeError and sends no packets
    beurer_instance._is_on = False
    with pytest.raises(RuntimeError, match="Cannot enable timer when the lamp is off"):
        await beurer_instance.enable_timer()
    assert len(sent_packets) == 0

    # Calling enable_timer when lamp is on sends duration and enable packets
    beurer_instance._is_on = True
    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance.enable_timer()

    assert beurer_instance.timer_active is True
    assert beurer_instance.timer_minutes_remaining == 30
    assert len(sent_packets) == 2
    pkt1 = list(sent_packets[0])
    pkt2 = list(sent_packets[1])
    assert pkt1[7] == 0x38  # CMD_ENABLE_TIMER
    assert pkt1[8] == 0x01
    assert pkt2[7] == 0x33  # CMD_SET_TIMER_DURATION
    assert pkt2[8] == 0x01  # CHANNEL_WHITE
    assert pkt2[9] == 30

    # Test disable timer when lamp is on
    sent_packets.clear()
    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance.disable_timer()

    assert beurer_instance.timer_active is False
    assert beurer_instance.timer_minutes_remaining == 0
    assert len(sent_packets) == 2
    assert list(sent_packets[0])[7] == 0x36  # CMD_DISABLE_TIMER white
    assert list(sent_packets[0])[8] == 0x01
    assert list(sent_packets[1])[7] == 0x36  # CMD_DISABLE_TIMER color
    assert list(sent_packets[1])[8] == 0x02

    # Test disable timer when lamp is off resets state without sending packets
    sent_packets.clear()
    beurer_instance._is_on = False
    beurer_instance._timer_active = True
    beurer_instance._timer_minutes_remaining = 30
    await beurer_instance.disable_timer()
    assert beurer_instance.timer_active is False
    assert beurer_instance.timer_minutes_remaining == 0
    assert len(sent_packets) == 0

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
async def test_set_color_brightness_enables_color_channel_when_off(beurer_instance: BeurerInstance) -> None:
    """Test set_color_brightness enables color channel if not previously on."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._color_on = False

    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance.set_color_brightness(200)

    assert len(sent_packets) == 2
    pkt1 = list(sent_packets[0])
    assert pkt1[7] == 0x37
    assert pkt1[8] == 0x02
    assert beurer_instance._color_brightness == 200

@pytest.mark.asyncio
async def test_set_color_enables_color_channel_when_off(beurer_instance: BeurerInstance) -> None:
    """Test set_color enables color channel if not previously on."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._color_on = False
    beurer_instance._light_on = False

    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance.set_color((0, 255, 0))

    # Expect enable channel (0x37 0x02) and set color (0x32 ...)
    assert len(sent_packets) == 2
    pkt1 = list(sent_packets[0])
    assert pkt1[7] == 0x37
    assert pkt1[8] == 0x02
    assert beurer_instance.is_on is True

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

@pytest.mark.asyncio
async def test_set_effect(beurer_instance: BeurerInstance) -> None:
    """Test set_effect switches to RGB mode, turns off white, and sets effect."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance.set_effect("Rainbow")

    # Packet 1: disable white (0x35 0x01)
    # Packet 2: enable color (0x37 0x02)
    # Packet 3: set effect (0x34 ...)
    assert len(sent_packets) == 3
    assert beurer_instance.color_mode == ColorMode.RGB
    assert beurer_instance.effect == "Rainbow"
    assert beurer_instance.is_on is True

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
async def test_set_white_enables_white_channel_when_off(beurer_instance: BeurerInstance) -> None:
    """Test set_white enables white channel if not previously on."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._light_on = False
    beurer_instance._color_on = False

    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance.set_white(180)

    assert len(sent_packets) == 2
    pkt1 = list(sent_packets[0])
    assert pkt1[7] == 0x37
    assert pkt1[8] == 0x01
    assert beurer_instance.white_brightness == 180

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
    assert beurer_instance.rgb_color == (255, 255, 255)
    assert beurer_instance.effect == "Off"

@pytest.mark.asyncio
async def test_timer_properties_and_duration_configuration(beurer_instance: BeurerInstance) -> None:
    """Test timer properties, validation of presets, and duration configuration."""
    assert beurer_instance.timer_duration == 15
    assert beurer_instance.timer_active is False
    assert beurer_instance.timer_minutes_remaining == 0

    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._mode = ColorMode.WHITE
    beurer_instance._color_on = False
    beurer_instance._is_on = True

    # Set valid duration to 45 min
    await beurer_instance.set_timer_duration(45)
    assert beurer_instance.timer_duration == 45
    assert len(sent_packets) == 1
    pkt = list(sent_packets[0])
    assert pkt[7] == 0x33  # CMD_SET_TIMER_DURATION
    assert pkt[8] == 0x01  # CHANNEL_WHITE
    assert pkt[9] == 45

    # Set valid duration to 7 min (arbitrary minute values supported)
    sent_packets.clear()
    await beurer_instance.set_timer_duration(7)
    assert beurer_instance.timer_duration == 7
    assert len(sent_packets) == 1
    pkt7 = list(sent_packets[0])
    assert pkt7[7] == 0x33  # CMD_SET_TIMER_DURATION
    assert pkt7[8] == 0x01  # CHANNEL_WHITE
    assert pkt7[9] == 7

    # Setting duration out of range raises ValueError
    with pytest.raises(ValueError, match="Timer duration must be between 1 and 120 minutes"):
        await beurer_instance.set_timer_duration(0)

    with pytest.raises(ValueError, match="Timer duration must be between 1 and 120 minutes"):
        await beurer_instance.set_timer_duration(150)

    # When lamp is off, setting duration stores value without sending packets
    sent_packets.clear()
    beurer_instance._is_on = False
    await beurer_instance.set_timer_duration(30)
    assert beurer_instance.timer_duration == 30
    assert len(sent_packets) == 0

    # Setting duration while timer active updates minutes remaining
    beurer_instance._is_on = True
    beurer_instance._timer_active = True
    await beurer_instance.set_timer_duration(90)
    assert beurer_instance.timer_duration == 90
    assert beurer_instance.timer_minutes_remaining == 90

    # In RGB mode, routes to color channel
    sent_packets.clear()
    beurer_instance._mode = ColorMode.RGB
    await beurer_instance.set_timer_duration(120)
    pkt_rgb = list(sent_packets[0])
    assert pkt_rgb[8] == 0x02  # CHANNEL_COLOR
    assert pkt_rgb[9] == 120

@pytest.mark.asyncio
async def test_turn_off(beurer_instance: BeurerInstance) -> None:
    """Test turn_off disables both channels and resets state."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = True

    await beurer_instance.turn_off()

    assert len(sent_packets) == 2
    pkt1 = list(sent_packets[0])
    pkt2 = list(sent_packets[1])
    assert pkt1[7] == 0x35
    assert pkt1[8] == 0x01  # Disable white
    assert pkt2[7] == 0x35
    assert pkt2[8] == 0x02  # Disable color
    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False
    assert beurer_instance.color_mode == ColorMode.WHITE

@pytest.mark.asyncio
async def test_turn_on_defaults_to_white_mode(beurer_instance: BeurerInstance) -> None:
    """Test that turn_on defaults to white daylight channel and initializes brightness."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance.triggerStatus = AsyncMock()

    await beurer_instance.turn_on()

    assert len(sent_packets) == 2
    pkt1 = list(sent_packets[0])
    assert pkt1[7] == 0x37
    assert pkt1[8] == 0x01
    pkt2 = list(sent_packets[1])
    assert pkt2[7] == 0x31
    assert pkt2[8] == 0x01
    assert beurer_instance.color_mode == ColorMode.WHITE
    assert beurer_instance.white_brightness == 255

@pytest.mark.asyncio
async def test_turn_on_in_rgb_mode(beurer_instance: BeurerInstance) -> None:
    """Test turn_on in RGB mode restores color, effect, and brightness."""
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._device = None

    async def mock_connect() -> bool:
        mock_dev = MagicMock()
        mock_dev.is_connected = True
        beurer_instance._device = mock_dev
        return True

    beurer_instance.connect = AsyncMock(side_effect=mock_connect)
    beurer_instance._mode = ColorMode.RGB
    beurer_instance._effect = "Rainbow"
    beurer_instance._color_brightness = 150
    beurer_instance._rgb_color = (0, 128, 255)

    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance.turn_on()

    beurer_instance.connect.assert_awaited_once()
    assert beurer_instance.is_on is True
    # Enables color, sets effect, sets brightness
    assert len(sent_packets) == 3

    # Now test with effect="Off" to exercise set_color branch
    sent_packets.clear()
    beurer_instance._effect = "Off"
    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance.turn_on()

    assert len(sent_packets) == 3
    pkt_color = list(sent_packets[1])
    assert pkt_color[7] == 0x32  # CMD_SET_COLOR

