"""Tests for incoming GATT notifications and device event handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.light import ColorMode

from custom_components.beurer.beurer import BeurerInstance
from custom_components.beurer.const import (
    CHANNEL_COLOR,
    CHANNEL_OFF,
    CHANNEL_SHUTDOWN,
    CHANNEL_WHITE,
    CMD_EVENT_LIGHT_TIMER_END,
    CMD_EVENT_MOONLIGHT_TIMER_END,
)


@pytest.mark.asyncio
async def test_button_turn_off_followed_by_reconnect_does_not_turn_on(
    beurer_instance: BeurerInstance,
) -> None:
    """Test physical button turn off keeps lamp off through BLE disconnect and reconnect without sending turn-on."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    # 1. Physical button pressed while lamp is on: emits 0xE8
    e8_payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0B,
            0xAB,
            0xBB,
            0x06,
            0xE8,
            0x00,
            0x00,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )
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
        patch(
            "custom_components.beurer.beurer.establish_connection",
            AsyncMock(return_value=mock_client),
        ),
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
async def test_button_turn_on_followed_by_reconnect_and_status_query_preserves_on_state(
    beurer_instance: BeurerInstance,
) -> None:
    """Test physical button turn on preserves ON state through BLE disconnect and status query."""
    beurer_instance._is_on = False
    beurer_instance._light_on = False
    beurer_instance._color_on = False

    # 1. Physical button pressed: emits 0xE8
    e8_payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0B,
            0xAB,
            0xBB,
            0x06,
            0xE8,
            0x00,
            0x00,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )
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
        [
            0xFE,
            0xEF,
            0x0C,
            0x0D,
            0xAB,
            0xBB,
            0x08,
            0xD0,
            0x01,
            0x01,
            0x64,
            0x00,
            0x00,
            0xBC,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    beurer_instance._last_notification_data = None
    await beurer_instance.notification_handler(char, ch1_payload)
    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True


@pytest.mark.asyncio
async def test_notification_burst_deduplication(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that identical notifications received within 0.3s are ignored to eliminate burst log storms."""
    char = MagicMock()
    update_count = 0

    def on_update() -> None:
        nonlocal update_count
        update_count += 1

    beurer_instance.set_update_callback(on_update)
    beurer_instance._is_on = False

    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0B,
            0xAB,
            0xBB,
            0x06,
            0xE8,
            0x00,
            0x00,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )

    # First packet is handled
    await beurer_instance.notification_handler(char, payload)
    assert update_count == 1

    # Identical packets in the 5x retransmission burst are ignored
    for _ in range(5):
        await beurer_instance.notification_handler(char, payload)

    assert update_count == 1


@pytest.mark.asyncio
async def test_notification_handler_boundary_conditions(
    beurer_instance: BeurerInstance,
) -> None:
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
            char,
            bytearray([0xFE, 0xEF, 0x0C, 0x08, 0xAB, 0xBB, 0x03, 0xD0, 0x99, 0x01]),
        )
        assert any("unknown notification channel" in str(call).lower() for call in mock_logger.debug.call_args_list)


@pytest.mark.asyncio
async def test_notification_handler_channel_1_off_status_packet(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that a status packet with channel 1 and state 0 turns off daylight."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    # Status packet: cmd 0xD0, channel 1 (daylight), state 0 (off), brightness 40
    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0D,
            0xAB,
            0xBB,
            0x08,
            0xD0,
            0x01,
            0x00,
            0x28,
            0x00,
            0x78,
            0x89,
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
            0x3D,
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
async def test_notification_handler_channel_color(
    beurer_instance: BeurerInstance,
) -> None:
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
async def test_notification_handler_channel_color_timer_status(
    beurer_instance: BeurerInstance,
) -> None:
    """Test notification_handler parses timer active and remaining fields on color channel."""
    char = MagicMock()

    # Color channel status packet with timer active (res[11]=0x01) and 18 minutes remaining (res[12]=0x12)
    data = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x12,
            0xAB,
            0xBB,
            0x0D,
            0xD0,  # CMD_STATUS_RESPONSE
            0x02,  # CHANNEL_COLOR
            0x01,  # State ON
            0x50,  # Brightness
            0x01,  # Timer active
            0x12,  # Timer minutes remaining = 18
            0xFF,
            0x00,
            0x00,  # RGB
            0x01,  # Scene
            0x00,
            0x00,
            0x00,
        ]
    )

    await beurer_instance.notification_handler(char, data)
    assert beurer_instance.timer_active is True
    assert beurer_instance.timer_minutes_remaining == 18

    # Color channel turns off while white channel is off -> timer resets
    off_data = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x12,
            0xAB,
            0xBB,
            0x0D,
            0xD0,
            0x02,
            0x00,  # State OFF
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )
    await beurer_instance.notification_handler(char, off_data)
    assert beurer_instance.timer_active is False
    assert beurer_instance.timer_minutes_remaining == 0


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
async def test_notification_handler_channel_shutdown(
    beurer_instance: BeurerInstance,
) -> None:
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
async def test_notification_handler_channel_white(
    beurer_instance: BeurerInstance,
) -> None:
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
async def test_notification_handler_channel_white_timer_status(
    beurer_instance: BeurerInstance,
) -> None:
    """Test notification_handler parses timer active and remaining fields on white channel."""
    char = MagicMock()

    # White channel status packet starting timer with valid preset 45 min (res[11]=0x01, res[12]=0x2D)
    start_data = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0E,
            0xAB,
            0xBB,
            0x09,
            0xD0,  # CMD_STATUS_RESPONSE
            0x01,  # CHANNEL_WHITE
            0x01,  # State ON
            0x50,  # Brightness
            0x01,  # Timer active
            0x2D,  # Timer minutes remaining = 45 (preset)
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )
    await beurer_instance.notification_handler(char, start_data)
    assert beurer_instance.timer_active is True
    assert beurer_instance.timer_minutes_remaining == 45
    assert beurer_instance.timer_duration == 45

    # White channel status packet with timer countdown 42 minutes remaining (res[12]=0x2A)
    data = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0E,
            0xAB,
            0xBB,
            0x09,
            0xD0,  # CMD_STATUS_RESPONSE
            0x01,  # CHANNEL_WHITE
            0x01,  # State ON
            0x50,  # Brightness
            0x01,  # Timer active
            0x2A,  # Timer minutes remaining = 42
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )

    await beurer_instance.notification_handler(char, data)
    assert beurer_instance.timer_active is True
    assert beurer_instance.timer_minutes_remaining == 42
    # Timer preset remains 45 during countdown
    assert beurer_instance.timer_duration == 45

    # White channel turns off while color channel is off -> timer resets
    off_data = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0E,
            0xAB,
            0xBB,
            0x09,
            0xD0,
            0x01,
            0x00,  # State OFF
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )
    await beurer_instance.notification_handler(char, off_data)
    assert beurer_instance.timer_active is False
    assert beurer_instance.timer_minutes_remaining == 0


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

    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0B,
            0xAB,
            0xBB,
            0x06,
            0xE8,
            0x00,
            0x00,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    char = MagicMock()

    # First 0xE8 packet turns on
    await beurer_instance.notification_handler(char, payload)
    assert beurer_instance.is_on is True
    assert update_count == 1

    # Burst of identical 0xE8 notifications in quick succession should be ignored
    for _ in range(10):
        await beurer_instance.notification_handler(char, payload)

    # Different payload bytes with same 0xE8 opcode hits duplicate command check
    payload_diff_e8 = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0B,
            0xAB,
            0xBB,
            0x06,
            0xE8,
            0x00,
            0x00,
            0x01,
            0xEF,
            0x55,
            0x0D,
            0x0A,
        ]
    )
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
async def test_notification_handler_event_e8_toggles_off(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling event 0xE8 toggles light off when already on."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0B,
            0xAB,
            0xBB,
            0x06,
            0xE8,
            0x00,
            0x00,
            0x00,
            0xEE,
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
async def test_notification_handler_event_e8_turns_on_sets_brightness(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling event 0xE8 toggles light on and initializes brightness."""
    beurer_instance._is_on = False
    beurer_instance._brightness = None

    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0B,
            0xAB,
            0xBB,
            0x06,
            0xE8,
            0x00,
            0x00,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._mode == ColorMode.WHITE
    assert beurer_instance._brightness == 255


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

    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x09,
            0xAB,
            0xBB,
            0x04,
            CMD_EVENT_LIGHT_TIMER_END,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    char = MagicMock()

    await beurer_instance.notification_handler(char, payload)
    assert beurer_instance.is_on is False
    assert update_count == 1

    # Burst of identical 0xEB notifications in quick succession should be ignored
    for _ in range(5):
        await beurer_instance.notification_handler(char, payload)

    # Different payload bytes with same 0xEB opcode hits duplicate command check
    payload_diff_eb = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x09,
            0xAB,
            0xBB,
            0x04,
            CMD_EVENT_LIGHT_TIMER_END,
            0x01,
            0xEF,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    await beurer_instance.notification_handler(char, payload_diff_eb)

    assert beurer_instance.is_on is False
    assert update_count == 1


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

    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x09,
            0xAB,
            0xBB,
            0x04,
            CMD_EVENT_LIGHT_TIMER_END,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is False
    assert beurer_instance._color_on is True
    assert callback_called is True


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
    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x09,
            0xAB,
            0xBB,
            0x04,
            CMD_EVENT_LIGHT_TIMER_END,
            0x00,
            0xEE,
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

    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x09,
            0xAB,
            0xBB,
            0x04,
            CMD_EVENT_MOONLIGHT_TIMER_END,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    char = MagicMock()

    await beurer_instance.notification_handler(char, payload)
    assert beurer_instance.is_on is False
    assert update_count == 1

    # Burst of identical 0xEC notifications in quick succession should be ignored
    for _ in range(5):
        await beurer_instance.notification_handler(char, payload)

    # Different payload bytes with same 0xEC opcode hits duplicate command check
    payload_diff_ec = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x09,
            0xAB,
            0xBB,
            0x04,
            CMD_EVENT_MOONLIGHT_TIMER_END,
            0x01,
            0xEF,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    await beurer_instance.notification_handler(char, payload_diff_ec)

    assert beurer_instance.is_on is False
    assert update_count == 1


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

    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x09,
            0xAB,
            0xBB,
            0x04,
            CMD_EVENT_MOONLIGHT_TIMER_END,
            0x00,
            0xEE,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._color_on is False
    assert callback_called is True


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
    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x09,
            0xAB,
            0xBB,
            0x04,
            CMD_EVENT_MOONLIGHT_TIMER_END,
            0x00,
            0xEE,
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
    assert callback_called is True


@pytest.mark.asyncio
async def test_notification_handler_permission_response(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that permission responses (0xF0) are handled safely without corrupting state."""
    beurer_instance._is_on = False
    payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0xF0, 0x02, 0xF6, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is False


@pytest.mark.asyncio
async def test_notification_handler_short_ack_packet_preserves_state(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that short write-ACK packets (e.g. 04 37 01) do not modify state."""
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False

    # Short 37 01 write ACK packet
    payload_37 = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0x37, 0x01, 0x32, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload_37)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance._color_on is False


@pytest.mark.asyncio
async def test_notification_handler_short_packet(
    beurer_instance: BeurerInstance,
) -> None:
    """Test handling malformed short packets without raising exceptions."""
    char = MagicMock()
    await beurer_instance.notification_handler(char, bytearray([0, 1, 2]))
    # Should safely return without crash


@pytest.mark.asyncio
async def test_notification_handler_short_status_packet_updates_state(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that a short status packet (payload_len=6) updates state correctly."""
    beurer_instance._is_on = False
    beurer_instance._light_on = False

    # payload_len = 6 (cmd 0xD0, channel 1, state 1, brightness 50)
    payload = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0B,
            0xAB,
            0xBB,
            0x06,
            0xD0,
            0x01,
            0x01,
            0x32,
            0xE4,
            0x55,
            0x0D,
            0x0A,
        ]
    )
    char = MagicMock()
    await beurer_instance.notification_handler(char, payload)

    assert beurer_instance.is_on is True
    assert beurer_instance._light_on is True
    assert beurer_instance.color_mode == ColorMode.WHITE
    assert beurer_instance.white_brightness == int(50 * 255 / 100)


@pytest.mark.asyncio
async def test_timer_reset_on_e8_shutdown_and_events(
    beurer_instance: BeurerInstance,
) -> None:
    """Test timer resets on button shutdown (0xE8) and timer-end notifications (0xEB, 0xEC)."""
    char = MagicMock()
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False
    beurer_instance._timer_active = True
    beurer_instance._timer_minutes_remaining = 30

    # 0xE8 turns off
    e8_payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0xE8, 0x00, 0xEC, 0x55, 0x0D, 0x0A])
    await beurer_instance.notification_handler(char, e8_payload)
    assert beurer_instance.timer_active is False
    assert beurer_instance.timer_minutes_remaining == 0

    # 0xEB daylight timer end
    beurer_instance._is_on = True
    beurer_instance._light_on = True
    beurer_instance._color_on = False
    beurer_instance._timer_active = True
    beurer_instance._timer_minutes_remaining = 10
    beurer_instance._last_notification_cmd = None
    eb_payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0xEB, 0x00, 0xEF, 0x55, 0x0D, 0x0A])
    await beurer_instance.notification_handler(char, eb_payload)
    assert beurer_instance.timer_active is False
    assert beurer_instance.timer_minutes_remaining == 0

    # 0xEC moodlight timer end
    beurer_instance._is_on = True
    beurer_instance._light_on = False
    beurer_instance._color_on = True
    beurer_instance._timer_active = True
    beurer_instance._timer_minutes_remaining = 10
    beurer_instance._last_notification_cmd = None
    ec_payload = bytearray([0xFE, 0xEF, 0x0C, 0x09, 0xAB, 0xBB, 0x04, 0xEC, 0x00, 0xE8, 0x55, 0x0D, 0x0A])
    await beurer_instance.notification_handler(char, ec_payload)
    assert beurer_instance.timer_active is False
    assert beurer_instance.timer_minutes_remaining == 0


@pytest.mark.asyncio
async def test_timer_duration_confirmation_tracks_lamp_state(
    beurer_instance: BeurerInstance,
) -> None:
    """Test the confirmed timer duration follows what the lamp acknowledged."""
    char = MagicMock()

    # Unknown until the lamp reports or the timer is enabled.
    assert beurer_instance._timer_lamp_duration is None

    # A white-channel status packet carrying 45 minutes confirms the duration.
    status = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0E,
            0xAB,
            0xBB,
            0x09,
            0xD0,  # CMD_STATUS_RESPONSE
            0x01,  # CHANNEL_WHITE
            0x01,  # State ON
            0x50,  # Brightness
            0x01,  # Timer active
            0x2D,  # 45 minutes remaining
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )
    await beurer_instance.notification_handler(char, status)
    assert beurer_instance._timer_lamp_duration == 45

    # The lamp turning the channel off clears the confirmed duration again.
    beurer_instance._last_notification_cmd = None
    off_status = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0E,
            0xAB,
            0xBB,
            0x09,
            0xD0,  # CMD_STATUS_RESPONSE
            0x01,  # CHANNEL_WHITE
            0x00,  # State OFF
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
    )
    await beurer_instance.notification_handler(char, off_status)
    assert beurer_instance._timer_lamp_duration is None


@pytest.mark.asyncio
async def test_event_e8_burst_guard_expires_after_window(
    beurer_instance: BeurerInstance,
) -> None:
    """Test a second real button press is honoured once the burst window passed.

    The burst guard used to be cleared only by a different opcode, so two
    consecutive presses of the physical button toggled the lamp once and then
    left the integration deaf to the button until some unrelated notification
    happened to arrive.
    """
    beurer_instance._is_on = False
    beurer_instance._light_on = False
    beurer_instance._color_on = False

    press_a = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x00, 0xEE, 0x55, 0x0D, 0x0A])
    # Same opcode, different trailing byte: a retransmission variant the
    # payload comparison cannot filter.
    press_b = bytearray([0xFE, 0xEF, 0x0C, 0x0B, 0xAB, 0xBB, 0x06, 0xE8, 0x00, 0x00, 0x01, 0xEF, 0x55, 0x0D, 0x0A])
    char = MagicMock()
    clock = [1000.0]

    with patch("custom_components.beurer.beurer.time.monotonic", lambda: clock[0]):
        await beurer_instance.notification_handler(char, press_a)
        assert beurer_instance.is_on is True

        # A retransmission variant 0.1 s later is still part of the same press.
        clock[0] += 0.1
        await beurer_instance.notification_handler(char, press_b)
        assert beurer_instance.is_on is True

        # A new press 1 s later must toggle the lamp off again.
        clock[0] += 1.0
        await beurer_instance.notification_handler(char, press_b)

    assert beurer_instance.is_on is False


@pytest.mark.asyncio
async def test_truncated_notification_is_ignored(
    beurer_instance: BeurerInstance,
) -> None:
    """Test a frame that declares more payload than it carries changes nothing.

    Without this guard the parser indexes straight past the end of the received
    bytes and could apply whatever the following bytes happen to be.
    """
    beurer_instance._is_on = False
    beurer_instance._light_on = False
    beurer_instance._color_on = False

    # Declares a 10 byte payload (0x0C) but stops after the channel byte. The
    # state byte at index 9 is still inside the received bytes, so without the
    # guard this would be parsed as "lamp on".
    truncated = bytearray([0xFE, 0xEF, 0x0C, 0x13, 0xAB, 0xAA, 0x0C, 0xD0, 0x01, 0x01])

    with patch("custom_components.beurer.beurer.LOGGER") as mock_logger:
        await beurer_instance.notification_handler(MagicMock(), truncated)

    assert beurer_instance.is_on is False
    assert beurer_instance._light_on is False
    assert any("truncated notification" in str(call).lower() for call in mock_logger.debug.call_args_list)


@pytest.mark.asyncio
async def test_checksum_mismatch_is_logged_but_still_processed(
    beurer_instance: BeurerInstance,
) -> None:
    """Test a checksum mismatch is reported without discarding the state update.

    BLE already covers frame integrity with a link-layer CRC, and no TL 100
    status capture has been confirmed to use the outgoing XOR convention. The
    log line exists to surface protocol drift; dropping the frame could freeze
    every entity instead.
    """
    beurer_instance._is_on = False
    beurer_instance._light_on = False
    beurer_instance._color_on = False

    packet = bytearray(
        [
            0xFE,
            0xEF,
            0x0C,
            0x0E,
            0xAB,
            0xBB,
            0x09,
            0xD0,  # status response
            0x01,  # white channel
            0x01,  # on
            0x32,  # brightness 50
            0x00,  # timer inactive
            0x00,  # no minutes
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,  # deliberately wrong checksum
        ]
    )

    with patch("custom_components.beurer.beurer.LOGGER") as mock_logger:
        await beurer_instance.notification_handler(MagicMock(), packet)

    assert beurer_instance.is_on is True
    assert any("checksum mismatch" in str(call).lower() for call in mock_logger.debug.call_args_list)
