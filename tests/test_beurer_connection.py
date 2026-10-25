"""Tests for connection, reconnection, disconnect and status polling."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bleak import BleakError, BLEDevice
from homeassistant.components.light import ColorMode

from custom_components.beurer.beurer import BeurerCommunicationError, BeurerInstance


@pytest.mark.asyncio
async def test_auto_reconnect_aborts_when_closing(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that auto-reconnect aborts if instance is marked as closing."""
    beurer_instance._closing = True
    beurer_instance.connect = AsyncMock()

    with patch("asyncio.sleep", AsyncMock()):
        await beurer_instance._auto_reconnect()

    beurer_instance.connect.assert_not_called()


@pytest.mark.asyncio
async def test_auto_reconnect_exception_handling(
    beurer_instance: BeurerInstance,
) -> None:
    """Test _auto_reconnect reports the first failure at INFO and repeats at DEBUG."""
    beurer_instance._closing = False
    beurer_instance._device = None
    beurer_instance.connect = AsyncMock(side_effect=RuntimeError("BLE connect failure"))

    with (
        patch("asyncio.sleep", AsyncMock()),
        patch("custom_components.beurer.beurer.LOGGER") as mock_logger,
    ):
        await beurer_instance._auto_reconnect()
        assert mock_logger.info.call_count == 1

        # A second failure of the same outage stays quiet on INFO.
        await beurer_instance._auto_reconnect()
        assert mock_logger.info.call_count == 1
        assert any("Reconnect attempt failed" in str(call) for call in mock_logger.debug.call_args_list)


@pytest.mark.asyncio
async def test_auto_reconnect_queries_both_channels(
    beurer_instance: BeurerInstance,
) -> None:
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
        patch(
            "custom_components.beurer.beurer.establish_connection",
            AsyncMock(return_value=mock_client),
        ),
        patch("asyncio.sleep", AsyncMock()),
    ):
        task = asyncio.create_task(beurer_instance._auto_reconnect())
        beurer_instance._reconnect_task = task
        await task

    assert sent_packets == [[0x30, 0x01], [0x30, 0x02]]
    assert task.done() is True
    assert not task.cancelled()


@pytest.mark.asyncio
async def test_auto_reconnect_respects_cooldown(
    beurer_instance: BeurerInstance,
) -> None:
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


def test_beurer_instance_stores_mac_from_device() -> None:
    """Test BeurerInstance takes the MAC address from the BLE device."""
    device = BLEDevice("57:4C:42:80:71:BA", "TL100_71BA")
    instance = BeurerInstance(device)
    assert instance.mac == "57:4C:42:80:71:BA"


@pytest.mark.asyncio
async def test_connect_already_connected_returns_true(
    beurer_instance: BeurerInstance,
) -> None:
    """Test connect returns True immediately if already connected with write UUID."""
    beurer_instance._device = MagicMock()
    beurer_instance._device.is_connected = True
    beurer_instance._write_uuid = "write-uuid"

    assert await beurer_instance.connect() is True


@pytest.mark.asyncio
async def test_connect_cancels_active_reconnect_task(
    beurer_instance: BeurerInstance,
) -> None:
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

    with patch(
        "custom_components.beurer.beurer.establish_connection",
        AsyncMock(return_value=mock_client),
    ):
        success = await beurer_instance.connect()

    assert success is True
    mock_task.cancel.assert_called_once()
    assert beurer_instance._reconnect_task is None


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
async def test_connect_does_not_cancel_own_reconnect_task(
    beurer_instance: BeurerInstance,
) -> None:
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

    with patch(
        "custom_components.beurer.beurer.establish_connection",
        AsyncMock(return_value=mock_client),
    ):
        success = await beurer_instance.connect()

    assert success is True
    assert beurer_instance._reconnect_task is current_task


@pytest.mark.asyncio
async def test_connect_fallback_without_bleak_retry_connector(
    beurer_instance: BeurerInstance,
) -> None:
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
async def test_connect_general_error_logs_error(
    beurer_instance: BeurerInstance,
) -> None:
    """Test connect logs error when unexpected exception occurs."""
    beurer_instance._device = None
    beurer_instance._write_uuid = None

    with (
        patch(
            "custom_components.beurer.beurer.establish_connection",
            AsyncMock(side_effect=BleakError("Hardware fault")),
        ),
        patch("custom_components.beurer.beurer.LOGGER") as mock_logger,
    ):
        result = await beurer_instance.connect()
        assert result is False
        # The first failure is reported once at INFO; a traceback is only logged on DEBUG.
        mock_logger.info.assert_called_once()
        mock_logger.error.assert_not_called()


@pytest.mark.asyncio
async def test_connect_handles_firmware_version_read_error(
    beurer_instance: BeurerInstance,
) -> None:
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

    with patch(
        "custom_components.beurer.beurer.establish_connection",
        AsyncMock(return_value=mock_client),
    ):
        success = await beurer_instance.connect()

    assert success is True
    mock_client.read_gatt_char.assert_awaited_once_with(char3.uuid)
    assert beurer_instance.firmware_version is None


@pytest.mark.asyncio
async def test_connect_missing_read_or_write_uuids(
    beurer_instance: BeurerInstance,
) -> None:
    """Test connect returns False if required UUIDs are not found."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    mock_client.services.characteristics.values.return_value = []

    beurer_instance._device = None
    beurer_instance._write_uuid = None

    with patch(
        "custom_components.beurer.beurer.establish_connection",
        AsyncMock(return_value=mock_client),
    ):
        result = await beurer_instance.connect()
        assert result is False


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

    with patch(
        "custom_components.beurer.beurer.establish_connection",
        AsyncMock(return_value=mock_client),
    ):
        success = await beurer_instance.connect()

    assert success is True
    mock_client.read_gatt_char.assert_awaited_once_with(char3.uuid)
    assert beurer_instance.firmware_version == "V1.35"


@pytest.mark.asyncio
async def test_connect_refuses_after_closing(beurer_instance: BeurerInstance) -> None:
    """Test a closed instance never reconnects, even if a write tries to.

    connect() used to clear _closing on entry. A write queued behind the unload
    therefore re-established the BLE link for an entry Home Assistant had
    already torn down, leaving a connection that nothing would ever close.
    """
    beurer_instance._closing = True
    beurer_instance._device = None

    with patch("custom_components.beurer.beurer.establish_connection", AsyncMock()) as establish:
        assert await beurer_instance.connect() is False

    establish.assert_not_called()
    assert beurer_instance._closing is True
    assert beurer_instance.available is False


@pytest.mark.asyncio
@pytest.mark.parametrize("software_first", [True, False])
async def test_connect_prefers_software_revision_over_firmware_revision(
    beurer_instance: BeurerInstance, software_first: bool
) -> None:
    """Test the software revision characteristic wins regardless of discovery order.

    Both 2A26 (firmware revision) and 2A28 (software revision) are part of the
    Device Information Service, and the TL 100 reports its version in the
    software revision. Picking whichever came last made the reported version
    depend on the order the stack enumerated characteristics in.
    """
    mock_client = MagicMock()
    mock_client.is_connected = True
    write_char = MagicMock()
    write_char.uuid = "8B00ACE7-EB0B-49B0-BBE9-9AEE0A26E1A3"
    read_char = MagicMock()
    read_char.uuid = "0734594A-A8E7-4B1A-A6B1-CD5243059A57"
    software_char = MagicMock()
    software_char.uuid = "00002A28-0000-1000-8000-00805F9B34FB"
    firmware_char = MagicMock()
    firmware_char.uuid = "00002A26-0000-1000-8000-00805F9B34FB"

    revision_chars = [software_char, firmware_char] if software_first else [firmware_char, software_char]
    mock_client.services.characteristics.values.return_value = [write_char, read_char, *revision_chars]
    mock_client.start_notify = AsyncMock()
    mock_client.read_gatt_char = AsyncMock(return_value=b"V1.35\x00\n")

    with patch(
        "custom_components.beurer.beurer.establish_connection",
        AsyncMock(return_value=mock_client),
    ):
        success = await beurer_instance.connect()

    assert success is True
    mock_client.read_gatt_char.assert_awaited_once_with(software_char.uuid)
    assert beurer_instance.firmware_version == "V1.35"


@pytest.mark.asyncio
async def test_connect_suppresses_already_shutdown_error(
    beurer_instance: BeurerInstance,
) -> None:
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

    with patch(
        "custom_components.beurer.beurer.establish_connection",
        AsyncMock(return_value=mock_client),
    ):
        success = await beurer_instance.connect()

    assert success is True
    mock_client.read_gatt_char.assert_not_awaited()
    assert beurer_instance.firmware_version is None


@pytest.mark.asyncio
async def test_disconnect_cancels_reconnect_task(
    beurer_instance: BeurerInstance,
) -> None:
    """Test disconnect cancels pending reconnect task."""
    mock_task = MagicMock()
    mock_task.done.return_value = False
    beurer_instance._reconnect_task = mock_task

    await beurer_instance.disconnect()
    mock_task.cancel.assert_called_once()
    assert beurer_instance._reconnect_task is None


@pytest.mark.asyncio
async def test_disconnect_handles_client_errors(
    beurer_instance: BeurerInstance,
) -> None:
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


def test_disconnected_callback_ignores_inactive_client(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that disconnected callback ignores disconnects from non-active client instances."""
    active_client = MagicMock()
    inactive_client = MagicMock()
    beurer_instance._device = active_client
    beurer_instance._is_on = True

    beurer_instance.disconnected_callback(inactive_client)

    assert beurer_instance._device is active_client
    assert beurer_instance.is_on is True


@pytest.mark.asyncio
async def test_disconnected_callback_ignores_when_connect_locked(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that disconnected callback is ignored while connect lock is held."""
    active_client = MagicMock()
    beurer_instance._device = active_client

    async with beurer_instance._connect_lock:
        beurer_instance.disconnected_callback(active_client)

    assert beurer_instance._device is active_client


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


def test_disconnected_callback_notifies_every_entity(beurer_instance: BeurerInstance) -> None:
    """Test a disconnect reaches all registered entities, not just the light.

    Only the light used to be notified, so the number, switch and sensor kept
    reporting their last values as available until the next poll.
    """
    mock_client = MagicMock()
    beurer_instance._device = mock_client
    called: list[str] = []
    beurer_instance.register_update_callback(lambda: called.append("light"))
    beurer_instance.register_update_callback(lambda: called.append("number"))
    beurer_instance.register_update_callback(lambda: called.append("switch"))
    beurer_instance.register_update_callback(lambda: called.append("sensor"))
    beurer_instance.trigger_reconnect = MagicMock()

    beurer_instance.disconnected_callback(mock_client)

    assert sorted(called) == ["light", "number", "sensor", "switch"]


def test_unregistered_entity_is_not_notified(beurer_instance: BeurerInstance) -> None:
    """Test a removed entity stops receiving updates."""
    called: list[str] = []
    unregister = beurer_instance.register_update_callback(lambda: called.append("removed"))

    unregister()
    beurer_instance.trigger_entity_update()

    assert called == []


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


def test_mac_and_supported_effects_properties(beurer_instance: BeurerInstance) -> None:
    """Test mac and supported_effects properties."""
    assert beurer_instance.mac == "57:4C:42:80:71:BA"
    assert "Rainbow" in beurer_instance.supported_effects


@pytest.mark.asyncio
async def test_multiple_update_callbacks(beurer_instance: BeurerInstance) -> None:
    """Test register_update_callback supports multiple callbacks, error isolation, and unregister."""
    cb1_called = False
    cb2_called = False

    def cb1() -> None:
        nonlocal cb1_called
        cb1_called = True
        raise RuntimeError("Callback 1 error")

    def cb2() -> None:
        nonlocal cb2_called
        cb2_called = True

    unreg1 = beurer_instance.register_update_callback(cb1)
    unreg2 = beurer_instance.register_update_callback(cb2)

    beurer_instance.trigger_entity_update()
    assert cb1_called is True
    assert cb2_called is True

    # Unregister cb1
    cb1_called = False
    cb2_called = False
    unreg1()

    beurer_instance.trigger_entity_update()
    assert cb1_called is False
    assert cb2_called is True
    unreg2()


@pytest.mark.asyncio
async def test_send_packet_connects_if_disconnected(
    beurer_instance: BeurerInstance,
) -> None:
    """Test sendPacket calls connect if client is disconnected."""
    beurer_instance._device = None
    beurer_instance.connect = AsyncMock(return_value=True)

    await beurer_instance.sendPacket([0x30, 0x01])
    beurer_instance.connect.assert_awaited_once()


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
            0x00,
            0x00,
            0x00,
            0x2B,
            0x55,
            0x0D,
            0x0A,
        ]
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
async def test_trigger_status_skips_color_channel_when_daylight_on(
    beurer_instance: BeurerInstance,
) -> None:
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
async def test_update_exception_calls_disconnect(
    beurer_instance: BeurerInstance,
) -> None:
    """Test update calls disconnect if triggerStatus raises exception."""
    beurer_instance._device = MagicMock()
    beurer_instance._device.is_connected = True
    beurer_instance.triggerStatus = AsyncMock(side_effect=RuntimeError("Protocol error"))
    beurer_instance.disconnect = AsyncMock()

    await beurer_instance.update()
    beurer_instance.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_queries_status_when_connected(
    beurer_instance: BeurerInstance,
) -> None:
    """Test that update queries status when the device is connected."""
    mock_client = MagicMock()
    mock_client.is_connected = True
    beurer_instance._device = mock_client
    beurer_instance.triggerStatus = AsyncMock()

    await beurer_instance.update()

    beurer_instance.triggerStatus.assert_awaited_once()


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
async def test_write_connect_failure(mock_device: BLEDevice) -> None:
    """Test _write raises when the connection cannot be established."""
    instance = BeurerInstance(mock_device)
    instance._device = None
    instance.connect = AsyncMock(return_value=False)

    with pytest.raises(BeurerCommunicationError, match="Could not connect"):
        await instance._write(bytearray([1, 2, 3]))


@pytest.mark.asyncio
async def test_write_timeout_raises_and_disconnects(mock_device: BLEDevice) -> None:
    """Test a GATT write timeout disconnects and surfaces as a communication error."""
    instance = BeurerInstance(mock_device)
    mock_client = MagicMock()
    mock_client.is_connected = True

    async def mock_write_timeout(*args: Any, **kwargs: Any) -> None:
        raise TimeoutError("GATT write timed out")

    mock_client.write_gatt_char = mock_write_timeout
    instance._device = mock_client
    instance._write_uuid = "write-uuid"
    instance.disconnect = AsyncMock()

    with pytest.raises(BeurerCommunicationError, match="Could not write"):
        await instance._write(bytearray([1, 2, 3]))
    instance.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_connection_loss_reported_once_per_outage(
    beurer_instance: BeurerInstance,
) -> None:
    """Test one outage produces a single INFO loss and a single INFO recovery."""
    beurer_instance._device = None
    beurer_instance._write_uuid = None
    beurer_instance.connect = AsyncMock(side_effect=RuntimeError("BLE connect failure"))

    with (
        patch("asyncio.sleep", AsyncMock()),
        patch("custom_components.beurer.beurer.LOGGER") as mock_logger,
    ):
        for _ in range(5):
            await beurer_instance._auto_reconnect()

        assert mock_logger.info.call_count == 1
        assert "Lost connection" in str(mock_logger.info.call_args)

        # A successful reconnect closes the outage and reports it once.
        beurer_instance._report_connection_restored()
        assert "Reconnected" in str(mock_logger.info.call_args)

        # The next outage is reported again.
        beurer_instance._report_connection_lost(RuntimeError("gone"))
        assert mock_logger.info.call_count == 3


@pytest.mark.asyncio
async def test_available_requires_active_connection(
    beurer_instance: BeurerInstance,
) -> None:
    """Test availability follows the live connection instead of advertisement state."""
    beurer_instance._device = None
    assert beurer_instance.available is False

    mock_client = MagicMock()
    mock_client.is_connected = True
    beurer_instance._device = mock_client
    # A connected client without a write characteristic cannot be controlled.
    beurer_instance._write_uuid = None
    assert beurer_instance.available is False

    beurer_instance._write_uuid = "write-uuid"
    assert beurer_instance.available is True

    # Closing the instance must never look controllable.
    beurer_instance._closing = True
    assert beurer_instance.available is False

    mock_client.is_connected = False
    beurer_instance._closing = False
    assert beurer_instance.available is False
