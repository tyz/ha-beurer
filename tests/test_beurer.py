"""Unit tests for Beurer communication instance."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError, BLEDevice
from custom_components.beurer.beurer import (
    BeurerInstance,
    create_status_callback,
    discover,
    get_device,
)
from custom_components.beurer.const import (
    CHANNEL_COLOR,
    CHANNEL_OFF,
    CHANNEL_SHUTDOWN,
    CHANNEL_WHITE,
    CMD_EVENT_LIGHT_TIMER_END,
    CMD_EVENT_MOONLIGHT_TIMER_END,
)
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
async def test_notification_handler_channel_white(beurer_instance: BeurerInstance) -> None:
    """Test handling status channel 1 (white daylight state)."""
    callback_called = False

    def update_callback() -> None:
        nonlocal callback_called
        callback_called = True

    beurer_instance.set_update_callback(update_callback)

    # res: [..., ..., ..., ..., ..., ..., ..., ..., channel=1, is_on=1, brightness=50]
    payload = bytearray([0] * 8 + [CHANNEL_WHITE, 1, 50])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance.color_mode == ColorMode.WHITE
    # 50% of 255 is 127
    assert beurer_instance.white_brightness == int(50 * 255 / 100)
    assert callback_called is True


@pytest.mark.asyncio
async def test_notification_handler_channel_color(beurer_instance: BeurerInstance) -> None:
    """Test handling status channel 2 (RGB color state)."""
    callback_called = False

    def update_callback() -> None:
        nonlocal callback_called
        callback_called = True

    beurer_instance.set_update_callback(update_callback)

    # channel=2, color_on=1, brightness=80, _, _, r=10, g=20, b=30, effect=2 (Rainbow)
    payload = bytearray([0] * 8 + [CHANNEL_COLOR, 1, 80, 0, 0, 10, 20, 30, 2])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance.color_mode == ColorMode.RGB
    assert beurer_instance.rgb_color == (10, 20, 30)
    assert beurer_instance.effect == "Rainbow"
    assert beurer_instance.color_brightness == int(80 * 255 / 100)
    assert callback_called is True

    # Switching to white daylight channel resets rgb_color to (255, 255, 255) and effect to "Off"
    payload_white = bytearray([0] * 8 + [CHANNEL_WHITE, 1, 90])
    beurer_instance._last_notification_data = None
    await beurer_instance.notification_handler(char, payload_white)
    assert beurer_instance.color_mode == ColorMode.WHITE
    assert beurer_instance.rgb_color == (255, 255, 255)
    assert beurer_instance.effect == "Off"


@pytest.mark.asyncio
async def test_notification_handler_channel_off_preserves_state(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling status channel 255 (empty/hardware ACK preserves state)."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    payload = bytearray([0] * 8 + [CHANNEL_OFF])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_handler_channel_shutdown(beurer_instance: BeurerInstance) -> None:
    """Test handling status channel 0 (device shutdown notification)."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = True

    payload = bytearray([0] * 8 + [CHANNEL_SHUTDOWN])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_handler_event_e8_turns_on_sets_brightness(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling event 0xE8 toggles light on and initializes brightness."""
    beurer_instance._is_on = False
    beurer_instance._brightness = None

    payload = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._mode == ColorMode.WHITE
    assert beurer_instance._brightness == 255


@pytest.mark.asyncio
async def test_notification_handler_event_e8_toggles_off(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling event 0xE8 toggles light off when already on."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    payload = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_handler_event_e8_ignores_duplicate_burst(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that rapid consecutive 0xE8 burst notifications are ignored."""
    beurer_instance._is_on = False
    update_count = 0

    def update_callback() -> None:
        nonlocal update_count
        update_count += 1

    beurer_instance.set_update_callback(update_callback)

    payload = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()

    # First 0xE8 packet turns on
    await beurer_instance.notification_handler(char, payload)
    assert beurer_instance.is_on is True
    assert update_count == 1

    # Burst of identical 0xE8 notifications in quick succession should be ignored
    for _ in range(10):
        await beurer_instance.notification_handler(char, payload)

    # Different payload bytes with same 0xE8 opcode hits duplicate command check
    payload_diff_e8 = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x01, 0xEF, 0x55, 0x0D, 0x0A])
    await beurer_instance.notification_handler(char, payload_diff_e8)

    assert beurer_instance.is_on is True
    assert update_count == 1

    # A non-0xE8 packet arrives (e.g. permission or status ACK)
    non_e8_payload = bytearray([0xFE, 0xEF, 0x0A, 0x08, 0xAB, 0xBB, 0x03, 0xF0, 0x02, 0x22, 0x55, 0x0D, 0x0A])
    await beurer_instance.notification_handler(char, non_e8_payload)

    # Next 0xE8 packet is now accepted and toggles off
    await beurer_instance.notification_handler(char, payload)
    assert beurer_instance.is_on is False
    assert update_count == 2


@pytest.mark.asyncio
async def test_notification_handler_event_eb_turns_off_daylight(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling event 0xEB turns off daylight channel."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False
    callback_called = False

    def update_callback() -> None:
        nonlocal callback_called
        callback_called = True

    beurer_instance.set_update_callback(update_callback)

    # Packet for 0xEB (RESPONSE_LIGHT_TIMER_END)
    payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, CMD_EVENT_LIGHT_TIMER_END, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False
    assert callback_called is True


@pytest.mark.asyncio
async def test_notification_handler_event_eb_preserves_moodlight_when_on(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling event 0xEB keeps light on if moodlight channel is active."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = True
    callback_called = False

    def update_callback() -> None:
        nonlocal callback_called
        callback_called = True

    beurer_instance.set_update_callback(update_callback)

    payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, CMD_EVENT_LIGHT_TIMER_END, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is True
    assert callback_called is True


@pytest.mark.asyncio
async def test_notification_handler_event_eb_ignores_duplicate_burst(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that rapid consecutive 0xEB burst notifications are ignored."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False
    update_count = 0

    def update_callback() -> None:
        nonlocal update_count
        update_count += 1

    beurer_instance.set_update_callback(update_callback)

    payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, CMD_EVENT_LIGHT_TIMER_END, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()

    await beurer_instance.notification_handler(char, payload)
    assert beurer_instance.is_on is False
    assert update_count == 1

    # Burst of identical 0xEB notifications in quick succession should be ignored
    for _ in range(5):
        await beurer_instance.notification_handler(char, payload)

    # Different payload bytes with same 0xEB opcode hits duplicate command check
    payload_diff_eb = bytearray(
        [0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, CMD_EVENT_LIGHT_TIMER_END, 0x01, 0xEF, 0x55, 0x0D, 0x0A]
    )
    await beurer_instance.notification_handler(char, payload_diff_eb)

    assert beurer_instance.is_on is False
    assert update_count == 1


@pytest.mark.asyncio
async def test_notification_handler_event_ec_turns_off_moodlight(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling event 0xEC turns off moodlight channel."""
    beurer_instance._is_on = True
    beurer_instance._light_on = False
    beurer_instance._color_on = True
    callback_called = False

    def update_callback() -> None:
        nonlocal callback_called
        callback_called = True

    beurer_instance.set_update_callback(update_callback)

    # Packet for 0xEC (RESPONSE_MOONLIGHT_TIMER_END)
    payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, CMD_EVENT_MOONLIGHT_TIMER_END, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False
    assert callback_called is True


@pytest.mark.asyncio
async def test_notification_handler_event_ec_preserves_daylight_when_on(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling event 0xEC keeps light on if daylight channel is active."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = True
    callback_called = False

    def update_callback() -> None:
        nonlocal callback_called
        callback_called = True

    beurer_instance.set_update_callback(update_callback)

    payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, CMD_EVENT_MOONLIGHT_TIMER_END, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._color_on is False
    assert callback_called is True


@pytest.mark.asyncio
async def test_notification_handler_event_ec_ignores_duplicate_burst(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that rapid consecutive 0xEC burst notifications are ignored."""
    beurer_instance._is_on = True
    beurer_instance._light_on = False
    beurer_instance._color_on = True
    update_count = 0

    def update_callback() -> None:
        nonlocal update_count
        update_count += 1

    beurer_instance.set_update_callback(update_callback)

    payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, CMD_EVENT_MOONLIGHT_TIMER_END, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()

    await beurer_instance.notification_handler(char, payload)
    assert beurer_instance.is_on is False
    assert update_count == 1

    # Burst of identical 0xEC notifications in quick succession should be ignored
    for _ in range(5):
        await beurer_instance.notification_handler(char, payload)

    # Different payload bytes with same 0xEC opcode hits duplicate command check
    payload_diff_ec = bytearray(
        [0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, CMD_EVENT_MOONLIGHT_TIMER_END, 0x01, 0xEF, 0x55, 0x0D, 0x0A]
    )
    await beurer_instance.notification_handler(char, payload_diff_ec)

    assert beurer_instance.is_on is False
    assert update_count == 1


def test_disconnected_callback_preserves_state(beurer_instance: BeurerInstance) -> None:
    """Test that disconnected callback resets connection without marking light as off."""
    mock_client = MagicMock()
    beurer_instance._device = mock_client
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    beurer_instance.disconnected_callback(mock_client)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._color_on is False
    assert beurer_instance._device is None
    assert beurer_instance._last_notification_cmd is None


def test_disconnected_callback_ignores_inactive_client(beurer_instance: BeurerInstance) -> None:
    """Test that disconnected callback ignores disconnects from non-active client instances."""
    active_client = MagicMock()
    inactive_client = MagicMock()
    beurer_instance._device = active_client
    beurer_instance._is_on = True

    beurer_instance.disconnected_callback(inactive_client)

    assert beurer_instance._device is active_client
    assert beurer_instance.is_on is True


@pytest.mark.asyncio
async def test_disconnected_callback_ignores_when_connect_locked(beurer_instance: BeurerInstance) -> None:
    """Test that disconnected callback is ignored while connect lock is held."""
    active_client = MagicMock()
    beurer_instance._device = active_client

    async with beurer_instance._connect_lock:
        beurer_instance.disconnected_callback(active_client)

    assert beurer_instance._device is active_client


@pytest.mark.asyncio
async def test_notification_handler_short_ack_packet_preserves_state(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that short write-ACK packets (e.g. 04 37 01) do not modify state."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    # Short 37 01 write ACK packet
    payload_37 = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0x37, 0x01, 0x2B, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload_37)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_handler_channel_off_preserves_other_active_channel(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that receiving 04 D0 FF for an inactive channel preserves the active channel."""
    # When white light is active, querying channel 2 (moodlight) returns 04 D0 FF
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False
    beurer_instance._last_queried_channel = 2

    payload_d0 = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0xD0, 0xFF, 0x2B, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload_d0)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._color_on is False

    # When moodlight is active, querying channel 1 (daylight) returns 04 D0 FF
    beurer_instance._is_on = True
    beurer_instance._light_on = False
    beurer_instance._color_on = True
    beurer_instance._last_queried_channel = 1

    await beurer_instance.notification_handler(char, payload_d0)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is True


@pytest.mark.asyncio
async def test_notification_handler_short_status_packet_updates_state(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that a short status packet (payload_len=6) updates state correctly."""
    beurer_instance._is_on = False
    beurer_instance._light_on = False

    # payload_len = 6 (cmd 0xD0, channel 1, state 1, brightness 50)
    payload = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xD0, 0x01, 0x01, 0x32, 0x00, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance.color_mode == ColorMode.WHITE
    assert beurer_instance.white_brightness == int(50 * 255 / 100)


@pytest.mark.asyncio
async def test_notification_handler_channel_1_off_status_packet(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that a status packet with channel 1 and state 0 turns off daylight."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    # Status packet: cmd 0xD0, channel 1 (daylight), state 0 (off), brightness 40
    payload = bytearray([0xFE, 0xEF, 0x0C, 0x0D, 0xAB, 0xBB, 0x08, 0xD0, 0x01, 0x00, 0x28, 0x00, 0x78, 0x2B, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_handler_channel_2_off_status_packet(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that a status packet with channel 2 and state 0 turns off moodlight."""
    beurer_instance._is_on = True
    beurer_instance._light_on = False
    beurer_instance._color_on = True

    # Status packet: cmd 0xD0, channel 2 (moodlight), state 0 (off), brightness 100
    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x11,
            0xAB,
            0xBB,
            0x0C,
            0xD0,
            0x02,
            0x00,
            0x64,
            0x00,
            0x78,
            0xFF,
            0x00,
            0x00,
            0x00,
            0x2B,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_button_turn_on_followed_by_reconnect_and_status_query_preserves_on_state(
    beurer_instance: BeurerInstance,
) -> None:
    """Test physical button turn on preserves ON state through BLE disconnect and status query."""
    beurer_instance._is_on = False
    beurer_instance._light_on = False
    beurer_instance._color_on = False

    # 1. Physical button pressed: emits 0xE8
    e8_payload = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, e8_payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    # Verifies no commands were written over BLE on button toggle (prevents firmware freeze)
    assert not beurer_instance._write.called

    # 2. Lamp disconnects ~2.2s later, disconnected_callback called
    mock_client = MagicMock()
    beurer_instance._device = mock_client
    beurer_instance.disconnected_callback(mock_client)
    assert beurer_instance.is_on is True

    # 3. Auto-reconnect queries channels:
    # Query channel 1: channel 255 (04 D0 FF) preserves light_on state
    d0_ff_payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0xD0, 0xFF, 0x2B, 0x55, 0x0D, 0x0A])
    beurer_instance._last_queried_channel = 1
    # Clear last notification time so it is not treated as a duplicate of e8_payload
    beurer_instance._last_notification_data = None
    await beurer_instance.notification_handler(char, d0_ff_payload)
    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True

    # When active status arrives, state is updated
    ch1_payload = bytearray(
        [0xFE, 0xEF, 0x0C, 0x0D, 0xAB, 0xBB, 0x08, 0xD0, 0x01, 0x01, 0x64, 0x00, 0x00, 0x2B, 0x55, 0x0D, 0x0A]
    )
    beurer_instance._last_notification_data = None
    await beurer_instance.notification_handler(char, ch1_payload)
    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True


@pytest.mark.asyncio
async def test_button_turn_off_followed_by_reconnect_does_not_turn_on(
    beurer_instance: BeurerInstance,
) -> None:
    """Test physical button turn off keeps lamp off through BLE disconnect and reconnect without sending turn-on."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    # 1. Physical button pressed while lamp is on: emits 0xE8
    e8_payload = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, e8_payload)

    # State is turned off
    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert not beurer_instance._write.called

    # 2. Lamp disconnects ~2.2s later, disconnected_callback triggers auto-reconnect
    mock_client = MagicMock()
    mock_client.is_connected = True
    char1 = MagicMock()
    char1.uuid = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    mock_client.services.characteristics.values.return_value = [char1, char2]
    mock_client.start_notify = AsyncMock()

    sent_packets: list[list[int]] = []

    async def mock_send(packet: list[int]) -> None:
        sent_packets.append(packet)
        if beurer_instance._status_response_event is not None:
            beurer_instance._status_response_event.set()

    beurer_instance.sendPacket = mock_send
    beurer_instance._device = mock_client

    with (
        patch("custom_components.beurer.beurer.establish_connection", AsyncMock(return_value=mock_client)),
        patch("asyncio.sleep", AsyncMock()),
    ):
        beurer_instance.disconnected_callback(mock_client)
        assert beurer_instance.is_on is False
        assert beurer_instance._reconnect_task is not None
        await beurer_instance._reconnect_task

    # Crucial: CMD_ENABLE_CHANNEL (0x37 0x01) was NOT sent, only status queries
    assert sent_packets == [[0x30, 0x01], [0x30, 0x02]]
    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_burst_deduplication(beurer_instance: BeurerInstance) -> None:
    """Test that identical notifications received within 0.3s are ignored to eliminate burst log storms."""
    char = MagicMock()
    update_count = 0

    def on_update() -> None:
        nonlocal update_count
        update_count += 1

    beurer_instance.set_update_callback(on_update)
    beurer_instance._is_on = False

    payload = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x00, 0xEE, 0x55, 0x0D, 0x0A])

    # First packet is handled
    await beurer_instance.notification_handler(char, payload)
    assert update_count == 1

    # Identical packets in the 5x retransmission burst are ignored
    for _ in range(5):
        await beurer_instance.notification_handler(char, payload)

    assert update_count == 1


@pytest.mark.asyncio
async def test_trigger_status_skips_color_channel_when_daylight_on(beurer_instance: BeurerInstance) -> None:
    """Test that triggerStatus skips querying color channel when daylight is already active."""
    sent_packets: list[list[int]] = []

    async def mock_send(packet: list[int]) -> None:
        sent_packets.append(packet)
        if beurer_instance._status_response_event is not None:
            beurer_instance._status_response_event.set()

    beurer_instance.sendPacket = mock_send
    beurer_instance._last_status_trigger = 0.0
    beurer_instance._light_on = True

    await beurer_instance.triggerStatus()
    # Daylight is active, so only channel 1 status is queried
    assert sent_packets == [[0x30, 0x01]]


@pytest.mark.asyncio
async def test_notification_handler_permission_response(beurer_instance: BeurerInstance) -> None:
    """Test that permission responses (0xF0) are handled safely without corrupting state."""
    beurer_instance._is_on = False
    payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0xF0, 0x02, 0x2B, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False


@pytest.mark.asyncio
async def test_notification_handler_short_packet(beurer_instance: BeurerInstance) -> None:
    """Test handling malformed short packets without raising exceptions."""
    char = MagicMock()
    await beurer_instance.notification_handler(char, bytearray([0, 1, 2]))
    # Should safely return without crash


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
async def test_write_handles_timeout_gracefully(mock_device: BLEDevice) -> None:
    """Test that _write handles timeout during GATT write without crashing."""
    instance = BeurerInstance(mock_device)
    mock_client = MagicMock()
    mock_client.is_connected = True

    async def mock_write_timeout(*args: Any, **kwargs: Any) -> None:
        raise TimeoutError("GATT write timed out")

    mock_client.write_gatt_char = mock_write_timeout
    instance._device = mock_client
    instance._write_uuid = "write-uuid"
    instance.disconnect = AsyncMock()

    # Should safely catch TimeoutError and call disconnect
    await instance._write(bytearray([1, 2, 3]))
    instance.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_cancels_active_reconnect_task(beurer_instance: BeurerInstance) -> None:
    """Test that a successful connect cancels any pending auto-reconnect task."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    char1 = MagicMock()
    char1.uuid = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    mock_client.services.characteristics.values.return_value = [char1, char2]
    mock_client.start_notify = AsyncMock()

    mock_task = MagicMock()
    mock_task.done.return_value = False
    beurer_instance._reconnect_task = mock_task

    with patch("custom_components.beurer.beurer.establish_connection", AsyncMock(return_value=mock_client)):
        success = await beurer_instance.connect()

    assert success is True
    mock_task.cancel.assert_called_once()
    assert beurer_instance._reconnect_task is None


@pytest.mark.asyncio
async def test_connect_does_not_cancel_own_reconnect_task(beurer_instance: BeurerInstance) -> None:
    """Test that connect does not cancel its own task when run as auto-reconnect task."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    char1 = MagicMock()
    char1.uuid = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    mock_client.services.characteristics.values.return_value = [char1, char2]
    mock_client.start_notify = AsyncMock()

    current_task = asyncio.current_task()
    beurer_instance._reconnect_task = current_task

    with patch("custom_components.beurer.beurer.establish_connection", AsyncMock(return_value=mock_client)):
        success = await beurer_instance.connect()

    assert success is True
    assert beurer_instance._reconnect_task is current_task


@pytest.mark.asyncio
async def test_trigger_status_defers_entity_update_until_complete(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that triggerStatus updates entity once after both channels are queried without mid-query off flicker."""
    update_calls: list[bool] = []

    def update_callback() -> None:
        update_calls.append(beurer_instance.is_on)

    beurer_instance.set_update_callback(update_callback)
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = None

    payload_ch1_off = bytearray(
        [0xFE, 0xEF, 0x0C, 0x0D, 0xAB, 0xBB, 0x08, 0xD0, 0x01, 0x00, 0x00, 0x00, 0x00, 0x2B, 0x55, 0x0D, 0x0A]
    )
    payload_ch2_on = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x13,
            0xAB,
            0xBB,
            0x0E,
            0xD0,
            0x02,
            0x01,
            0x3C,
            0x00,
            0x00,
            0xFF,
            0x00,
            0x00,
            0x00,
            0x55,
            0x0D,
            0x0A,
        ]
    )

    async def mock_send(packet: list[int]) -> None:
        char = MagicMock()
        if packet == [0x30, 0x01]:
            await beurer_instance.notification_handler(char, payload_ch1_off)
        elif packet == [0x30, 0x02]:
            await beurer_instance.notification_handler(char, payload_ch2_on)

    beurer_instance.sendPacket = mock_send
    beurer_instance._last_status_trigger = 0.0

    await beurer_instance.triggerStatus()

    # Callback must be called exactly once at the end of triggerStatus
    assert len(update_calls) == 1
    assert update_calls == [True]
    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is True
    assert beurer_instance.color_mode == ColorMode.RGB


@pytest.mark.asyncio
async def test_auto_reconnect_queries_both_channels(beurer_instance: BeurerInstance) -> None:
    """Test that auto-reconnect does not cancel itself and successfully queries both channels."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    char1 = MagicMock()
    char1.uuid = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    mock_client.services.characteristics.values.return_value = [char1, char2]
    mock_client.start_notify = AsyncMock()

    sent_packets: list[list[int]] = []

    async def mock_send(packet: list[int]) -> None:
        sent_packets.append(packet)
        if beurer_instance._status_response_event is not None:
            beurer_instance._status_response_event.set()

    beurer_instance.sendPacket = mock_send
    beurer_instance._device = None
    beurer_instance._write_uuid = None
    beurer_instance._read_uuid = None

    with (
        patch("custom_components.beurer.beurer.establish_connection", AsyncMock(return_value=mock_client)),
        patch("asyncio.sleep", AsyncMock()),
    ):
        task = asyncio.create_task(beurer_instance._auto_reconnect())
        beurer_instance._reconnect_task = task
        await task

    assert sent_packets == [[0x30, 0x01], [0x30, 0x02]]
    assert task.done() is True
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_connect_disables_services_cache(beurer_instance: BeurerInstance) -> None:
    """Test that connect calls establish_connection with use_services_cache=False."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    char1 = MagicMock()
    char1.uuid = "8B00ACE7-EB0B-49B0-BBE9-9AEE0A26E1A3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    mock_client.services.characteristics.values.return_value = [char1, char2]
    mock_client.start_notify = AsyncMock()

    mock_establish = AsyncMock(return_value=mock_client)
    with patch("custom_components.beurer.beurer.establish_connection", mock_establish):
        success = await beurer_instance.connect()

    assert success is True
    mock_establish.assert_called_once()
    assert mock_establish.call_args.kwargs.get("use_services_cache") is False


@pytest.mark.asyncio
async def test_connect_reads_firmware_version(beurer_instance: BeurerInstance) -> None:
    """Test that connect reads the software revision characteristic and populates firmware_version."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    char1 = MagicMock()
    char1.uuid = "8B00ACE7-EB0B-49B0-BBE9-9AEE0A26E1A3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    char3 = MagicMock()
    char3.uuid = "00002A28-0000-1000-8000-00805F9B34FB"
    mock_client.services.characteristics.values.return_value = [char1, char2, char3]
    mock_client.start_notify = AsyncMock()
    mock_client.read_gatt_char = AsyncMock(return_value=b"V1.35\x00\n")

    with patch("custom_components.beurer.beurer.establish_connection", AsyncMock(return_value=mock_client)):
        success = await beurer_instance.connect()

    assert success is True
    mock_client.read_gatt_char.assert_awaited_once_with(char3.uuid)
    assert beurer_instance.firmware_version == "V1.35"


@pytest.mark.asyncio
async def test_connect_handles_firmware_version_read_error(beurer_instance: BeurerInstance) -> None:
    """Test that connect succeeds even if reading firmware version fails."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    char1 = MagicMock()
    char1.uuid = "8B00ACE7-EB0B-49B0-BBE9-9AEE0A26E1A3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    char3 = MagicMock()
    char3.uuid = "00002A28-0000-1000-8000-00805F9B34FB"
    mock_client.services.characteristics.values.return_value = [char1, char2, char3]
    mock_client.start_notify = AsyncMock()
    mock_client.read_gatt_char = AsyncMock(side_effect=BleakError("Read failed"))

    with patch("custom_components.beurer.beurer.establish_connection", AsyncMock(return_value=mock_client)):
        success = await beurer_instance.connect()

    assert success is True
    mock_client.read_gatt_char.assert_awaited_once_with(char3.uuid)
    assert beurer_instance.firmware_version is None


@pytest.mark.asyncio
async def test_connect_when_version_characteristic_missing(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that connect succeeds and leaves firmware_version as None when characteristic is missing."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    char1 = MagicMock()
    char1.uuid = "8B00ACE7-EB0B-49B0-BBE9-9AEE0A26E1A3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    char3 = MagicMock()
    char3.uuid = "e06d5efb-4f4a-45c0-9eb1-371ae5a14ad4"
    char3.properties = ["read"]
    mock_client.services.characteristics.values.return_value = [char1, char2, char3]
    mock_client.start_notify = AsyncMock()
    mock_client.read_gatt_char = AsyncMock()

    with patch("custom_components.beurer.beurer.establish_connection", AsyncMock(return_value=mock_client)):
        success = await beurer_instance.connect()

    assert success is True
    mock_client.read_gatt_char.assert_not_awaited()
    assert beurer_instance.firmware_version is None


@pytest.mark.asyncio
async def test_trigger_status_debounced(beurer_instance: BeurerInstance) -> None:
    """Test that triggerStatus debounces multiple rapid calls."""
    sent_packets: list[list[int]] = []

    async def mock_send(packet: list[int]) -> None:
        sent_packets.append(packet)
        if beurer_instance._status_response_event is not None:
            beurer_instance._status_response_event.set()

    beurer_instance.sendPacket = mock_send
    beurer_instance._last_status_trigger = 0.0

    # First call: should send two status packets [0x30, 0x01] and [0x30, 0x02]
    await beurer_instance.triggerStatus()
    assert len(sent_packets) == 2
    assert sent_packets == [[0x30, 0x01], [0x30, 0x02]]

    # Second immediate call: should be debounced and not send more packets
    await beurer_instance.triggerStatus()
    assert len(sent_packets) == 2


@pytest.mark.asyncio
async def test_disconnect_stops_notifications_and_disconnects_cleanly(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that disconnect stops notifications and cleanly disconnects active client."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.stop_notify = AsyncMock()
    mock_client.disconnect = AsyncMock()

    beurer_instance._device = mock_client
    beurer_instance._read_uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    beurer_instance._write_uuid = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
    beurer_instance._is_on = True

    await beurer_instance.disconnect(closing=True)

    mock_client.stop_notify.assert_awaited_once_with("0734594A-A8E7-4B1A-A6B1-CD5243059A57")
    mock_client.disconnect.assert_awaited_once()
    assert beurer_instance._closing is True
    assert beurer_instance._device is None
    assert beurer_instance.is_on is False


@pytest.mark.asyncio
async def test_disconnect_transient_does_not_mark_closing(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that disconnect without closing=True resets client but keeps _closing False."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.stop_notify = AsyncMock()
    mock_client.disconnect = AsyncMock()

    beurer_instance._device = mock_client
    beurer_instance._read_uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    beurer_instance._write_uuid = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
    beurer_instance._is_on = True

    await beurer_instance.disconnect(closing=False)

    mock_client.stop_notify.assert_awaited_once_with("0734594A-A8E7-4B1A-A6B1-CD5243059A57")
    mock_client.disconnect.assert_awaited_once()
    assert beurer_instance._closing is False
    assert beurer_instance._device is None
    assert beurer_instance.is_on is False


@pytest.mark.asyncio
async def test_disconnect_prevents_auto_reconnect_on_subsequent_callbacks(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that disconnect prevents auto-reconnect from being scheduled."""
    beurer_instance._closing = True
    mock_client = MagicMock()
    beurer_instance._device = mock_client

    beurer_instance.disconnected_callback(mock_client)

    assert beurer_instance._reconnect_task is None


@pytest.mark.asyncio
async def test_auto_reconnect_aborts_when_closing(beurer_instance: BeurerInstance) -> None:
    """Test that auto-reconnect aborts if instance is marked as closing."""
    beurer_instance._closing = True
    beurer_instance.connect = AsyncMock()

    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance._auto_reconnect()

    beurer_instance.connect.assert_not_called()


@pytest.mark.asyncio
async def test_auto_reconnect_respects_cooldown(beurer_instance: BeurerInstance) -> None:
    """Test that auto-reconnect sleeps for at least the remaining cooldown period."""
    beurer_instance._device = None
    beurer_instance.connect = AsyncMock(return_value=False)
    beurer_instance._last_reconnect_time = 100.0

    with (
        patch("time.monotonic", return_value=102.0),
        patch("asyncio.sleep", AsyncMock()) as mock_sleep,
    ):
        await beurer_instance._auto_reconnect()
        # elapsed is 2.0s, remaining cooldown should be 5.0 - 2.0 = 3.0s
        mock_sleep.assert_awaited_once_with(3.0)
        assert beurer_instance._last_reconnect_time == 102.0


def test_is_connected_property(beurer_instance: BeurerInstance) -> None:
    """Test that is_connected reflects the connection state of the BleakClient."""
    assert beurer_instance.is_connected is True

    beurer_instance._device = None
    assert beurer_instance.is_connected is False

    mock_client = MagicMock()
    mock_client.is_connected = False
    beurer_instance._device = mock_client
    assert beurer_instance.is_connected is False

    mock_client.is_connected = True
    assert beurer_instance.is_connected is True


@pytest.mark.asyncio
async def test_update_skips_when_disconnected(beurer_instance: BeurerInstance) -> None:
    """Test that update triggers background reconnect and skips status update when disconnected."""
    beurer_instance._device = None
    beurer_instance.connect = AsyncMock()
    beurer_instance.triggerStatus = AsyncMock()
    beurer_instance.trigger_reconnect = MagicMock()

    await beurer_instance.update()

    beurer_instance.trigger_reconnect.assert_called_once()
    beurer_instance.connect.assert_not_called()
    beurer_instance.triggerStatus.assert_not_called()


@pytest.mark.asyncio
async def test_update_queries_status_when_connected(beurer_instance: BeurerInstance) -> None:
    """Test that update queries status when the device is connected."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    beurer_instance._device = mock_client
    beurer_instance.triggerStatus = AsyncMock()

    await beurer_instance.update()

    beurer_instance.triggerStatus.assert_awaited_once()


@pytest.mark.asyncio
async def test_trigger_reconnect_lifecycle(beurer_instance: BeurerInstance) -> None:
    """Test trigger_reconnect scheduling and closing guard."""
    beurer_instance._closing = True
    beurer_instance.trigger_reconnect()
    assert beurer_instance._reconnect_task is None

    beurer_instance._closing = False
    beurer_instance.trigger_reconnect()
    assert beurer_instance._reconnect_task is not None
    beurer_instance._reconnect_task.cancel()


@pytest.mark.asyncio
async def test_connect_suppresses_already_shutdown_error(beurer_instance: BeurerInstance) -> None:
    """Test that connection error during shutdown is logged as debug instead of error."""
    with (
        patch(
            "custom_components.beurer.beurer.establish_connection",
            side_effect=BleakError("Failed to connect after 3 attempt(s): Bluetooth is already shutdown"),
        ),
        patch("custom_components.beurer.beurer.LOGGER") as mock_logger,
    ):
        result = await beurer_instance.connect()
        assert result is False
        mock_logger.error.assert_not_called()
        assert any("shutdown" in str(call).lower() for call in mock_logger.debug.call_args_list)


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
async def test_get_device_function() -> None:
    """Test get_device finds device by mac address or returns None."""
    dev1 = MagicMock()
    dev1.address = "AA:BB:CC:DD:EE:FF"

    with patch("custom_components.beurer.beurer.BleakScanner.discover", AsyncMock(return_value=[dev1])):
        result = await get_device("aa:bb:cc:dd:ee:ff")
        assert result is dev1

        result_none = await get_device("00:11:22:33:44:55")
        assert result_none is None


def test_beurer_instance_none_device() -> None:
    """Test BeurerInstance handles None device gracefully."""
    with patch("custom_components.beurer.beurer.LOGGER") as mock_logger:
        instance = BeurerInstance(None)
        assert instance.mac == ""
        mock_logger.error.assert_called_once()


def test_disconnected_callback_triggers_update(beurer_instance: BeurerInstance) -> None:
    """Test disconnected_callback calls update callback if registered."""
    mock_client = MagicMock()
    beurer_instance._device = mock_client
    update_called = False

    def on_update() -> None:
        nonlocal update_called
        update_called = True

    beurer_instance.set_update_callback(on_update)
    beurer_instance.trigger_reconnect = MagicMock()

    beurer_instance.disconnected_callback(mock_client)
    assert update_called is True


@pytest.mark.asyncio
async def test_auto_reconnect_exception_handling(beurer_instance: BeurerInstance) -> None:
    """Test _auto_reconnect catches exception from connect and logs debug."""
    beurer_instance._closing = False
    beurer_instance._device = None
    beurer_instance.connect = AsyncMock(side_effect=RuntimeError("BLE connect failure"))

    with (
        patch("asyncio.sleep", AsyncMock()),
        patch("custom_components.beurer.beurer.LOGGER") as mock_logger,
    ):
        await beurer_instance._auto_reconnect()
        assert any("Auto-reconnect attempt failed" in str(call) for call in mock_logger.debug.call_args_list)


@pytest.mark.asyncio
async def test_write_connect_failure(mock_device: BLEDevice) -> None:
    """Test _write logs error and returns if connect fails."""
    instance = BeurerInstance(mock_device)
    instance._device = None
    instance.connect = AsyncMock(return_value=False)

    with patch("custom_components.beurer.beurer.LOGGER") as mock_logger:
        await instance._write(bytearray([1, 2, 3]))
        mock_logger.error.assert_called_once()


def test_mac_and_supported_effects_properties(beurer_instance: BeurerInstance) -> None:
    """Test mac and supported_effects properties."""
    assert beurer_instance.mac == "57:4C:42:80:71:BA"
    assert "Rainbow" in beurer_instance.supported_effects


@pytest.mark.asyncio
async def test_send_packet_connects_if_disconnected(beurer_instance: BeurerInstance) -> None:
    """Test sendPacket calls connect if client is disconnected."""
    beurer_instance._device = None
    beurer_instance.connect = AsyncMock(return_value=True)

    await beurer_instance.sendPacket([0x30, 0x01])
    beurer_instance.connect.assert_awaited_once()


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
async def test_trigger_status_timeouts(beurer_instance: BeurerInstance) -> None:
    """Test triggerStatus handles TimeoutError gracefully when lamp does not respond."""
    beurer_instance.sendPacket = AsyncMock()
    beurer_instance._last_status_trigger = 0.0
    beurer_instance._light_on = False

    async def mock_wait_for(fut_or_coro: Any, timeout: float | None = None) -> Any:
        if asyncio.iscoroutine(fut_or_coro):
            fut_or_coro.close()
        raise TimeoutError()

    with patch("asyncio.wait_for", mock_wait_for):
        await beurer_instance.triggerStatus(force=True)

    assert beurer_instance._last_queried_channel is None


@pytest.mark.asyncio
async def test_connect_already_connected_returns_true(beurer_instance: BeurerInstance) -> None:
    """Test connect returns True immediately if already connected with write UUID."""
    beurer_instance._device = MagicMock()
    beurer_instance._device.is_connected = True
    beurer_instance._write_uuid = "write-uuid"

    assert await beurer_instance.connect() is True


@pytest.mark.asyncio
async def test_connect_fallback_without_bleak_retry_connector(beurer_instance: BeurerInstance) -> None:
    """Test connect fallback path when BleakRetryConnector is unavailable."""
    mock_client = MagicMock()
    mock_client.is_connected = False
    mock_client.connect = AsyncMock()
    char1 = MagicMock()
    char1.uuid = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
    char2 = MagicMock()
    char2.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    mock_client.services.characteristics.values.return_value = [char1, char2]
    mock_client.start_notify = AsyncMock()

    beurer_instance._device = None
    beurer_instance._write_uuid = None

    with (
        patch("custom_components.beurer.beurer.HAVE_BLEAK_RETRY_CONNECTOR", False),
        patch("custom_components.beurer.beurer.BleakClient", return_value=mock_client),
    ):
        result = await beurer_instance.connect()
        assert result is True
        mock_client.connect.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_missing_read_or_write_uuids(beurer_instance: BeurerInstance) -> None:
    """Test connect returns False if required UUIDs are not found."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.services.characteristics.values.return_value = []

    beurer_instance._device = None
    beurer_instance._write_uuid = None

    with patch("custom_components.beurer.beurer.establish_connection", AsyncMock(return_value=mock_client)):
        result = await beurer_instance.connect()
        assert result is False


@pytest.mark.asyncio
async def test_connect_general_error_logs_error(beurer_instance: BeurerInstance) -> None:
    """Test connect logs error when unexpected exception occurs."""
    beurer_instance._device = None
    beurer_instance._write_uuid = None

    with (
        patch("custom_components.beurer.beurer.establish_connection", AsyncMock(side_effect=BleakError("Hardware fault"))),
        patch("custom_components.beurer.beurer.LOGGER") as mock_logger,
    ):
        result = await beurer_instance.connect()
        assert result is False
        mock_logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_update_exception_calls_disconnect(beurer_instance: BeurerInstance) -> None:
    """Test update calls disconnect if triggerStatus raises exception."""
    beurer_instance._device = MagicMock()
    beurer_instance._device.is_connected = True
    beurer_instance.triggerStatus = AsyncMock(side_effect=RuntimeError("Protocol error"))
    beurer_instance.disconnect = AsyncMock()

    await beurer_instance.update()
    beurer_instance.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_disconnect_cancels_reconnect_task(beurer_instance: BeurerInstance) -> None:
    """Test disconnect cancels pending reconnect task."""
    mock_task = MagicMock()
    mock_task.done.return_value = False
    beurer_instance._reconnect_task = mock_task

    await beurer_instance.disconnect()
    mock_task.cancel.assert_called_once()
    assert beurer_instance._reconnect_task is None


@pytest.mark.asyncio
async def test_disconnect_handles_client_errors(beurer_instance: BeurerInstance) -> None:
    """Test disconnect catches errors from stop_notify and disconnect without raising."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.stop_notify = AsyncMock(side_effect=BleakError("GATT stop failed"))
    mock_client.disconnect = AsyncMock(side_effect=BleakError("BLE disconnect failed"))

    beurer_instance._device = mock_client
    beurer_instance._read_uuid = "read-uuid"

    await beurer_instance.disconnect()
    assert beurer_instance._device is None


@pytest.mark.asyncio
async def test_notification_handler_boundary_conditions(beurer_instance: BeurerInstance) -> None:
    """Test notification_handler handles edge case payloads safely."""
    char = MagicMock()

    # Payload length <= IDX_CHANNEL (<= 8)
    await beurer_instance.notification_handler(char, bytearray([0xFE, 0xEF, 0x0C, 0x06, 0xAB, 0xBB, 0x01, 0xD0]))

    # Payload with channel white but len <= IDX_STATE (<= 9)
    await beurer_instance.notification_handler(char, bytearray([0xFE, 0xEF, 0x0C, 0x07, 0xAB, 0xBB, 0x02, 0xD0, 0x01]))

    # Payload with channel color but len <= IDX_STATE (<= 9)
    await beurer_instance.notification_handler(char, bytearray([0xFE, 0xEF, 0x0C, 0x07, 0xAB, 0xBB, 0x02, 0xD0, 0x02]))

    # Unknown channel
    with patch("custom_components.beurer.beurer.LOGGER") as mock_logger:
        await beurer_instance.notification_handler(
            char, bytearray([0xFE, 0xEF, 0x0C, 0x08, 0xAB, 0xBB, 0x03, 0xD0, 0x99, 0x01])
        )
        assert any("unknown notification channel" in str(call).lower() for call in mock_logger.debug.call_args_list)
