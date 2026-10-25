"""Tests for serialising logical commands and the timer duration race."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.components.light import ColorMode

from custom_components.beurer.beurer import BeurerInstance

# Status reply to 0x38 on channel 1 (white): lamp on at 50% brightness, timer
# active with 120 minutes, which is the firmware default right after enabling.
STATUS_TIMER_120_WHITE = bytearray(
    [
        0xFE,  # header 0
        0xEF,  # header 1
        0x0A,  # packet type
        0x0B,  # total length
        0xAB,  # sync 0
        0xAA,  # sync 1
        0x0D,  # payload length
        0xD0,  # opcode: status
        0x01,  # channel: white
        0x01,  # state: on
        0x32,  # brightness: 50
        0x01,  # timer active
        0x78,  # timer minutes: 120
        0x00,  # red
        0x00,  # green
        0x00,  # blue
        0x00,  # scene
        0x55,  # footer
        0x0D,
        0x0A,
    ]
)


@pytest.mark.asyncio
async def test_status_during_enable_timer_does_not_change_duration(
    beurer_instance: BeurerInstance,
) -> None:
    """Test a status reply arriving during enable_timer keeps the chosen duration.

    The lamp answers 0x38 with a status packet reporting its own 120 minute
    default. That reply must not overwrite the duration the user picked, or the
    following 0x33 would programme 120 minutes instead.
    """
    sent_packets: list[bytearray] = []

    async def mock_write(data: bytearray) -> None:
        sent_packets.append(data)

    beurer_instance._write = mock_write
    beurer_instance._mode = ColorMode.WHITE
    beurer_instance._color_on = False
    beurer_instance._light_on = True
    beurer_instance._is_on = True
    beurer_instance._timer_duration = 15

    async def sleep_and_notify(_delay: float) -> None:
        # Simulate the lamp answering 0x38 while the pause is running.
        await beurer_instance.notification_handler(MagicMock(), STATUS_TIMER_120_WHITE)

    with patch("asyncio.sleep", sleep_and_notify):
        await beurer_instance.enable_timer()

    assert len(sent_packets) == 2
    assert list(sent_packets[1])[7] == 0x33
    assert list(sent_packets[1])[9] == 15, "0x33 must carry the chosen duration, not the firmware default"
    assert beurer_instance.timer_duration == 15
    assert beurer_instance.timer_minutes_remaining == 15


@pytest.mark.asyncio
async def test_status_after_enable_timer_still_adopts_lamp_duration(
    beurer_instance: BeurerInstance,
) -> None:
    """Test the guard is released once enable_timer has finished.

    Adopting the lamp's duration outside a timer command is intended: it keeps
    the number entity in sync when the timer is started from the hardware.
    """
    beurer_instance._mode = ColorMode.WHITE
    beurer_instance._color_on = False
    beurer_instance._light_on = True
    beurer_instance._is_on = True
    beurer_instance._timer_duration = 15
    beurer_instance._timer_active = False

    await beurer_instance.notification_handler(MagicMock(), STATUS_TIMER_120_WHITE)

    assert beurer_instance.timer_duration == 120


@pytest.mark.asyncio
async def test_turn_off_cannot_interleave_between_timer_frames(
    beurer_instance: BeurerInstance,
) -> None:
    """Test a concurrent turn_off cannot slip between 0x38 and 0x33.

    Sending 0x33 to a lamp that has just been switched off hangs the firmware,
    so the two timer frames must form one uninterrupted sequence.
    """
    events: list[str] = []
    real_sleep = asyncio.sleep
    spawned: list[asyncio.Task[None]] = []

    async def mock_write(data: bytearray) -> None:
        events.append(f"write:{list(data)[7]:#04x}")

    beurer_instance._write = mock_write
    beurer_instance._mode = ColorMode.WHITE
    beurer_instance._color_on = False
    beurer_instance._light_on = True
    beurer_instance._is_on = True
    beurer_instance._timer_duration = 20

    async def sleep_and_turn_off(_delay: float) -> None:
        events.append("sleep")
        if not spawned:
            # Only the first pause races; later pauses are turn_off's own.
            spawned.append(asyncio.ensure_future(beurer_instance.turn_off()))
        # Give the competing task every chance to interleave.
        for _ in range(5):
            await real_sleep(0)

    with patch("asyncio.sleep", sleep_and_turn_off):
        await beurer_instance.enable_timer()
        await asyncio.gather(*spawned)

    assert events.index("write:0x38") < events.index("write:0x33"), events
    off_writes = [index for index, event in enumerate(events) if event == "write:0x35"]
    assert off_writes, f"turn_off never wrote: {events}"
    assert not (events.index("write:0x38") < off_writes[0] < events.index("write:0x33")), (
        f"turn_off interleaved with the timer sequence: {events}"
    )


@pytest.mark.asyncio
async def test_failed_write_reaches_the_entity_as_home_assistant_error(
    beurer_instance: BeurerInstance,
) -> None:
    """Test a write failure propagates instead of being swallowed.

    The entity layer translates BLE failures into HomeAssistantError, but that
    only works if the failure actually travels up through sendPacket(). Before,
    _write() logged the error and returned, so a command that never reached the
    lamp was reported as successful and the optimistic state was applied.
    """
    from bleak.exc import BleakError
    from homeassistant.exceptions import HomeAssistantError

    from custom_components.beurer.light import BeurerLight

    # The fixture replaces _write with a mock; this test needs the real one.
    del beurer_instance._write

    mock_client = MagicMock()
    mock_client.is_connected = True

    async def failing_write(*_args: Any, **_kwargs: Any) -> None:
        raise BleakError("lamp is out of range")

    mock_client.write_gatt_char = failing_write
    beurer_instance._device = mock_client
    beurer_instance._write_uuid = "write-uuid"
    beurer_instance._read_uuid = "read-uuid"
    beurer_instance._mode = ColorMode.WHITE
    beurer_instance._light_on = False
    beurer_instance._is_on = False

    light = BeurerLight(beurer_instance, "My Lamp", "entry_123")

    with pytest.raises(HomeAssistantError) as exc_info:
        await light.async_turn_on()

    assert exc_info.value.translation_key == "communication_error"
    assert beurer_instance.is_on is False, "state must not claim the lamp is on after a failed write"
