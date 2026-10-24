"""Low-level Bluetooth communication client for Beurer TL 100 lamps."""

from __future__ import annotations

import asyncio
import time
import traceback
from collections.abc import Callable

from bleak import (
    BleakClient,
    BleakError,
    BleakGATTCharacteristic,
    BleakScanner,
    BLEDevice,
)
from homeassistant.components.light import ColorMode

from .const import (
    CHANNEL_COLOR,
    CHANNEL_OFF,
    CHANNEL_SHUTDOWN,
    CHANNEL_WHITE,
    CMD_DISABLE_CHANNEL,
    CMD_ENABLE_CHANNEL,
    CMD_EVENT_LIGHT_TIMER_END,
    CMD_EVENT_MOONLIGHT_TIMER_END,
    CMD_EVENT_SHUTDOWN,
    CMD_PERMISSION_RESPONSE,
    CMD_QUERY_STATUS,
    CMD_SET_BRIGHTNESS,
    CMD_SET_COLOR,
    CMD_SET_EFFECT,
    CMD_STATUS_RESPONSE,
    EFFECTS,
    IDX_BLUE,
    IDX_BRIGHTNESS,
    IDX_CHANNEL,
    IDX_GREEN,
    IDX_HEADER_0,
    IDX_HEADER_1,
    IDX_OPCODE,
    IDX_PAYLOAD_LEN,
    IDX_RED,
    IDX_SCENE,
    IDX_STATE,
    LOGGER,
    PACKET_FOOTER,
    PACKET_HEADER,
    PACKET_SYNC_COMMAND,
    PACKET_TYPE_COMMAND,
    READ_CHARACTERISTIC_UUIDS,
    VERSION_CHARACTERISTIC_UUIDS,
    WRITE_CHARACTERISTIC_UUIDS,
    Channel,
)

try:
    from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

    HAVE_BLEAK_RETRY_CONNECTOR = True
except ImportError:
    HAVE_BLEAK_RETRY_CONNECTOR = False


async def discover() -> list[BLEDevice]:
    """Discover Beurer Bluetooth LE devices.

    Returns:
        List of discovered TL100 BLE devices.
    """
    devices = await BleakScanner.discover()
    LOGGER.debug("Discovered devices: %s", [{"address": device.address, "name": device.name} for device in devices])
    return [device for device in devices if device.name and device.name.lower().startswith("tl100")]


def create_status_callback(future: asyncio.Future[bytearray]) -> Callable[[int, bytearray], None]:
    """Create a callback for status futures.

    Args:
        future: The asyncio future to resolve on notification.

    Returns:
        A callback callable that accepts sender and data.
    """

    def callback(sender: int, data: bytearray) -> None:
        if not future.done():
            future.set_result(data)

    return callback


async def get_device(mac: str) -> BLEDevice | None:
    """Find a BLE device by MAC address.

    Args:
        mac: The MAC address string to look for.

    Returns:
        The matched BLEDevice or None if not found.
    """
    devices = await BleakScanner.discover()
    LOGGER.debug("Discovered devices: %s", devices)
    return next((device for device in devices if device.address.lower() == mac.lower()), None)


class BeurerInstance:
    """Handles communication and state for a single Beurer TL 100 device."""

    def __init__(self, device: BLEDevice) -> None:
        """Initialize the Beurer instance.

        Args:
            device: Underlying BLEDevice instance.
        """
        self._ble_device = device
        self._mac: str = device.address if device else ""
        if device is None:
            LOGGER.error("Was not able to find device with mac %s", self._mac)
        self._device: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._trigger_update: Callable[[], None] | None = None
        self._is_on: bool = False
        self._light_on: bool | None = None
        self._color_on: bool | None = None
        self._rgb_color: tuple[int, int, int] = (0, 0, 0)
        self._brightness: int | None = None
        self._color_brightness: int | None = None
        self._effect: str | None = None
        self._write_uuid: str | None = None
        self._read_uuid: str | None = None
        self._version_uuid: str | None = None
        self._firmware_version: str | None = None
        self._last_status_trigger: float = 0.0
        self._last_queried_channel: Channel | int | None = None
        self._status_response_event: asyncio.Event | None = None
        self._status_lock: asyncio.Lock = asyncio.Lock()
        self._last_notification_cmd: int | None = None
        self._last_notification_data: bytearray | None = None
        self._last_notification_time: float = 0.0
        self._hardware_mode_until: float = 0.0
        self._sync_channel_on_connect: bool = False
        self._channel_sync_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closing: bool = False
        self._last_reconnect_time: float = 0.0
        self._mode: ColorMode | None = ColorMode.WHITE
        self._supported_effects: list[str] = list(EFFECTS)

    def set_device(self, device: BLEDevice) -> None:
        """Update the underlying BLEDevice.

        Args:
            device: The new BLEDevice instance.
        """
        self._ble_device = device

    @property
    def is_connected(self) -> bool:
        """Return True if the BLE device is currently connected."""
        return self._device is not None and self._device.is_connected

    @property
    def is_closing(self) -> bool:
        """Return True if the instance is closing or disconnecting."""
        return self._closing

    @property
    def _hardware_mode(self) -> bool:
        """Return True if within the hardware-mode grace period following a physical toggle."""
        return time.monotonic() < self._hardware_mode_until

    @_hardware_mode.setter
    def _hardware_mode(self, value: bool) -> None:
        """Set hardware-mode grace period."""
        if value:
            self._hardware_mode_until = time.monotonic() + 15.0
        else:
            self._hardware_mode_until = 0.0

    def trigger_reconnect(self) -> None:
        """Schedule an auto-reconnect task if not already reconnecting."""
        if self._closing:
            return
        if self._reconnect_task is None or self._reconnect_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._reconnect_task = loop.create_task(self._auto_reconnect())
            except RuntimeError:
                pass

    def disconnected_callback(self, client: BleakClient) -> None:
        """Handle disconnection event from Bleak.

        Args:
            client: BleakClient that was disconnected.
        """
        if self._closing:
            LOGGER.debug("Ignoring disconnect callback because instance is closing/disconnected")
            return

        if self._device is None or client is not self._device:
            LOGGER.debug(
                "Ignoring disconnect callback from inactive client: %s (active: %s)",
                client,
                self._device,
            )
            return

        if self._connect_lock.locked():
            LOGGER.debug("Ignoring disconnect callback while connect lock is held")
            return

        LOGGER.debug("Disconnected callback called for active client")
        if self._channel_sync_task is not None and not self._channel_sync_task.done():
            self._channel_sync_task.cancel()
            self._channel_sync_task = None
        self._device = None
        self._write_uuid = None
        self._read_uuid = None
        self._last_notification_cmd = None
        self._last_notification_data = None
        if self._trigger_update:
            self._trigger_update()
        self.trigger_reconnect()

    def _cancel_channel_sync(self) -> None:
        """Cancel any pending deferred channel sync task and clear the sync flag."""
        self._sync_channel_on_connect = False
        if (
            self._channel_sync_task is not None
            and not self._channel_sync_task.done()
            and asyncio.current_task() != self._channel_sync_task
        ):
            self._channel_sync_task.cancel()
            self._channel_sync_task = None

    async def _deferred_channel_sync(self) -> None:
        """Sync channel state if device remains connected after physical button toggle."""
        await asyncio.sleep(2.5)
        if self._sync_channel_on_connect and self.is_connected:
            self._sync_channel_on_connect = False
            LOGGER.debug("Device remained connected after physical turn-on; syncing channel state")
            try:
                await self.sendPacket([CMD_ENABLE_CHANNEL, CHANNEL_WHITE])
                await asyncio.sleep(0.15)
                await self.triggerStatus(force=True)
            except Exception as err:  # noqa: BLE001
                LOGGER.debug("Deferred channel sync failed: %s", err)

    async def _auto_reconnect(self) -> None:
        """Attempt to reconnect after a short delay following disconnection."""
        now = time.monotonic()
        elapsed = now - self._last_reconnect_time
        delay = max(1.0, 5.0 - elapsed)
        LOGGER.debug("Scheduling auto-reconnect in %.1f seconds", delay)
        await asyncio.sleep(delay)
        if self._closing or self.is_connected:
            return
        self._last_reconnect_time = time.monotonic()
        LOGGER.debug("Executing auto-reconnect")
        try:
            if await self.connect():
                if self._sync_channel_on_connect:
                    self._sync_channel_on_connect = False
                    LOGGER.debug("Syncing white daylight channel state to BLE controller after physical turn on")
                    try:
                        await self.sendPacket([CMD_ENABLE_CHANNEL, CHANNEL_WHITE])
                        await asyncio.sleep(0.15)
                    except Exception as err:  # noqa: BLE001
                        LOGGER.debug("Channel sync after reconnect failed: %s", err)
                await self.triggerStatus(force=True)
        except Exception as error:  # noqa: BLE001
            LOGGER.debug("Auto-reconnect attempt failed: %s", error)

    def set_update_callback(self, trigger_update: Callable[[], None]) -> None:
        """Register the entity update callback.

        Args:
            trigger_update: Function to call when state updates occur.
        """
        LOGGER.debug("Setting update callback to %s", trigger_update)
        self._trigger_update = trigger_update

    async def _write(self, data: bytearray) -> None:
        """Send raw data to write characteristic.

        Args:
            data: Raw bytearray to write.
        """
        async with self._write_lock:
            LOGGER.debug(
                "Sending in write: %s to characteristic %s, device is %s",
                "".join(format(x, " 03x") for x in data),
                self._write_uuid,
                self._device.is_connected if self._device else False,
            )
            try:
                if (
                    self._device is None or not self._device.is_connected or self._write_uuid is None
                ) and not await self.connect():
                    LOGGER.error("Failed to connect before writing")
                    return
                if self._device and self._write_uuid:
                    async with asyncio.timeout(5.0):
                        await self._device.write_gatt_char(self._write_uuid, data)
            except (BleakError, TimeoutError, OSError) as error:
                track = traceback.format_exc()
                LOGGER.debug(track)
                LOGGER.warning("Error while trying to write to device: %s", error)
                await self.disconnect()

    @property
    def mac(self) -> str:
        """Return the device MAC address."""
        return self._mac

    @property
    def firmware_version(self) -> str | None:
        """Return device firmware version if known."""
        return self._firmware_version

    @property
    def is_on(self) -> bool:
        """Return True if any light channel is turned on."""
        return self._is_on

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return the current RGB color tuple."""
        return self._rgb_color

    @property
    def color_brightness(self) -> int | None:
        """Return current brightness in color mode."""
        return self._color_brightness

    @property
    def white_brightness(self) -> int | None:
        """Return current brightness in white mode."""
        return self._brightness

    @property
    def effect(self) -> str | None:
        """Return the active light effect name."""
        return self._effect

    @property
    def color_mode(self) -> ColorMode | None:
        """Return current ColorMode."""
        return self._mode

    @property
    def supported_effects(self) -> list[str]:
        """Return list of supported effect names."""
        return self._supported_effects

    def find_effect_position(self, effect: str) -> int:
        """Look up index position of an effect name.

        Args:
            effect: Name of the effect.

        Returns:
            The zero-based index or 0 if not found.
        """
        try:
            return self._supported_effects.index(effect)
        except ValueError:
            return 0

    def makeChecksum(self, b: int, bArr: list[int]) -> int:
        """Calculate packet XOR checksum.

        Args:
            b: Initial checksum value.
            bArr: List of integers to XOR against.

        Returns:
            Computed XOR checksum integer.
        """
        for b2 in bArr:
            b = b ^ b2
        return b

    async def sendPacket(self, message: list[int]) -> None:
        """Construct framing and checksum for payload and write to GATT.

        Args:
            message: Payload bytes as integer list.
        """
        if self._device is None or not self._device.is_connected:
            await self.connect()
        length = len(message)
        checksum = self.makeChecksum(length + 2, message)
        packet = (
            PACKET_HEADER
            + [PACKET_TYPE_COMMAND, length + 7]
            + PACKET_SYNC_COMMAND
            + [length + 2]
            + message
            + [checksum]
            + PACKET_FOOTER
        )
        LOGGER.debug("Sending message: %s", "".join(format(x, " 03x") for x in packet))
        await self._write(bytearray(packet))

    async def set_color(self, rgb: tuple[int, int, int]) -> None:
        """Set RGB color.

        Args:
            rgb: Red, Green, Blue tuple (0-255).
        """
        r, g, b = rgb
        LOGGER.debug("Setting to color: %s, %s, %s", r, g, b)
        self._mode = ColorMode.RGB
        self._rgb_color = (r, g, b)
        self._hardware_mode = False
        self._cancel_channel_sync()
        if self._light_on:
            # Turn off white daylight channel when switching to color mode
            await self.sendPacket([CMD_DISABLE_CHANNEL, CHANNEL_WHITE])
            self._light_on = False
            await asyncio.sleep(0.1)
        if not self._color_on:
            await self.sendPacket([CMD_ENABLE_CHANNEL, CHANNEL_COLOR])
            self._color_on = True
            await asyncio.sleep(0.1)
        await self.sendPacket([CMD_SET_COLOR, r, g, b])
        self._color_on = True
        self._is_on = True
        await self.trigger_entity_update()

    async def set_color_brightness(self, brightness: int) -> None:
        """Set brightness for RGB color channel.

        Args:
            brightness: Brightness scale from 0 to 255.
        """
        LOGGER.debug("Setting to brightness %s", brightness)
        self._mode = ColorMode.RGB
        self._hardware_mode = False
        self._cancel_channel_sync()
        if not self._color_on:
            await self.sendPacket([CMD_ENABLE_CHANNEL, CHANNEL_COLOR])
            self._color_on = True
            await asyncio.sleep(0.1)
        brightness_percent = max(0, min(100, int(brightness / 255 * 100)))
        await self.sendPacket([CMD_SET_BRIGHTNESS, CHANNEL_COLOR, brightness_percent])
        self._color_brightness = brightness
        self._color_on = True
        self._is_on = True
        await self.trigger_entity_update()

    async def set_white(self, intensity: int = 255) -> None:
        """Set white daylight intensity.

        Args:
            intensity: Brightness scale from 0 to 255.
        """
        LOGGER.debug("Setting white to intensity: %s", intensity)
        self._mode = ColorMode.WHITE
        self._hardware_mode = False
        self._cancel_channel_sync()
        if self._color_on:
            # Turn off color mode channel when switching to white daylight
            await self.sendPacket([CMD_DISABLE_CHANNEL, CHANNEL_COLOR])
            self._color_on = False
            await asyncio.sleep(0.1)
        if not self._light_on:
            await self.sendPacket([CMD_ENABLE_CHANNEL, CHANNEL_WHITE])
            self._light_on = True
            await asyncio.sleep(0.1)
        intensity_percent = max(0, min(100, int(intensity / 255 * 100)))
        # Cap at 99% to work around firmware bug where 100% in white mode
        # causes the device to switch to red/RGB mode (Deadolus#11)
        if intensity_percent == 100:
            intensity_percent = 99
        await self.sendPacket([CMD_SET_BRIGHTNESS, CHANNEL_WHITE, intensity_percent])
        self._brightness = intensity
        self._light_on = True
        self._is_on = True
        await self.trigger_entity_update()

    async def set_effect(self, effect: str) -> None:
        """Set effect mode on the lamp.

        Args:
            effect: Effect name string.
        """
        LOGGER.debug("Setting effect %s", effect)
        self._mode = ColorMode.RGB
        self._hardware_mode = False
        self._cancel_channel_sync()
        if self._light_on:
            # Turn off white daylight channel when switching to color mode
            await self.sendPacket([CMD_DISABLE_CHANNEL, CHANNEL_WHITE])
            self._light_on = False
            await asyncio.sleep(0.1)
        if not self._color_on:
            await self.sendPacket([CMD_ENABLE_CHANNEL, CHANNEL_COLOR])
            self._color_on = True
            await asyncio.sleep(0.1)
        await self.sendPacket([CMD_SET_EFFECT, self.find_effect_position(effect)])
        self._effect = effect
        self._color_on = True
        self._is_on = True
        await self.trigger_entity_update()

    async def turn_on(self) -> None:
        """Turn on the light in the current or saved mode."""
        LOGGER.debug("Turning on")
        self._hardware_mode = False
        self._cancel_channel_sync()
        if self._device is None or not self._device.is_connected:
            await self.connect()
        if self._mode == ColorMode.RGB:
            await self.sendPacket([CMD_ENABLE_CHANNEL, CHANNEL_COLOR])
            self._color_on = True
            if self._effect and self._effect != "Off":
                await asyncio.sleep(0.1)
                await self.sendPacket([CMD_SET_EFFECT, self.find_effect_position(self._effect)])
            elif self._rgb_color:
                await asyncio.sleep(0.1)
                await self.sendPacket([CMD_SET_COLOR, self._rgb_color[0], self._rgb_color[1], self._rgb_color[2]])
            if self._color_brightness is not None:
                await asyncio.sleep(0.1)
                brightness_percent = max(0, min(100, int(self._color_brightness / 255 * 100)))
                await self.sendPacket([CMD_SET_BRIGHTNESS, CHANNEL_COLOR, brightness_percent])
        else:
            self._mode = ColorMode.WHITE
            self._light_on = True
            if self._brightness is None:
                self._brightness = 255
            await self.sendPacket([CMD_ENABLE_CHANNEL, CHANNEL_WHITE])
            await asyncio.sleep(0.1)
            intensity_percent = max(0, min(99, int(self._brightness / 255 * 100)))
            await self.sendPacket([CMD_SET_BRIGHTNESS, CHANNEL_WHITE, intensity_percent])
        self._is_on = True
        await self.trigger_entity_update()

    async def turn_off(self) -> None:
        """Turn off both white and color channels."""
        LOGGER.debug("Turning off")
        self._hardware_mode = False
        self._cancel_channel_sync()
        await self.sendPacket([CMD_DISABLE_CHANNEL, CHANNEL_WHITE])
        await self.sendPacket([CMD_DISABLE_CHANNEL, CHANNEL_COLOR])
        self._mode = ColorMode.WHITE
        self._is_on = False
        self._light_on = False
        self._color_on = False
        await self.trigger_entity_update()

    async def triggerStatus(self, force: bool = False) -> None:
        """Request status updates from the device with debouncing.

        Args:
            force: If True, bypass the debouncing cooldown.
        """
        async with self._status_lock:
            now = time.monotonic()
            if not force and now - self._last_status_trigger < 2.0:
                LOGGER.debug("Skipping triggerStatus, called too recently")
                return
            self._last_status_trigger = now

            if self._status_response_event is None:
                self._status_response_event = asyncio.Event()

            try:
                self._last_queried_channel = CHANNEL_WHITE
                self._status_response_event.clear()
                await self.sendPacket([CMD_QUERY_STATUS, CHANNEL_WHITE])
                try:
                    await asyncio.wait_for(self._status_response_event.wait(), timeout=0.3)
                except TimeoutError:
                    pass

                # If white daylight is active, skip querying color channel (mutually exclusive on TL 100)
                if not self._light_on:
                    await asyncio.sleep(0.25)
                    self._last_queried_channel = CHANNEL_COLOR
                    self._status_response_event.clear()
                    await self.sendPacket([CMD_QUERY_STATUS, CHANNEL_COLOR])
                    try:
                        await asyncio.wait_for(self._status_response_event.wait(), timeout=0.3)
                    except TimeoutError:
                        pass
            finally:
                self._last_queried_channel = None
                self._is_on = bool(self._light_on or self._color_on)
                if self._is_on:
                    if self._light_on:
                        self._mode = ColorMode.WHITE
                    elif self._color_on:
                        self._mode = ColorMode.RGB
                LOGGER.info("Triggered update")
                await self.trigger_entity_update()

    async def trigger_entity_update(self) -> None:
        """Notify the entity callback of a state change."""
        if self._trigger_update:
            LOGGER.debug("Triggering async update")
            self._trigger_update()
        else:
            LOGGER.warning("No async update function provided: %s", self._trigger_update)

    async def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray) -> None:
        """Handle incoming GATT notifications from the device.

        Args:
            characteristic: Characteristic that produced the notification.
            data: Notification payload bytes.
        """
        now = time.monotonic()
        if (
            self._last_notification_data is not None
            and data == self._last_notification_data
            and now - self._last_notification_time < 0.3
        ):
            return
        self._last_notification_data = data
        self._last_notification_time = now

        LOGGER.debug("Received notification: %s", "".join(format(x, " 03x") for x in data))
        if len(data) <= IDX_OPCODE:
            return

        is_packet = len(data) >= 6 and data[IDX_HEADER_0] == PACKET_HEADER[0] and data[IDX_HEADER_1] == PACKET_HEADER[1]
        payload_len = data[IDX_PAYLOAD_LEN] if is_packet else len(data) - 7
        cmd = data[IDX_OPCODE]

        if cmd == CMD_EVENT_SHUTDOWN:
            if self._last_notification_cmd == CMD_EVENT_SHUTDOWN:
                LOGGER.debug("Ignoring duplicate 0xE8 burst notification")
                return
            self._last_notification_cmd = CMD_EVENT_SHUTDOWN
            new_state = not self._is_on
            LOGGER.debug(
                "Received device event 0xE8 (button toggle, is_on was %s -> now %s)",
                self._is_on,
                new_state,
            )
            self._is_on = new_state
            if not new_state:
                self._light_on = False
                self._color_on = False
                self._hardware_mode = False
                self._cancel_channel_sync()
            else:
                self._light_on = True
                self._color_on = False
                self._mode = ColorMode.WHITE
                self._hardware_mode = True
                self._sync_channel_on_connect = True
                if (
                    self._channel_sync_task is not None
                    and not self._channel_sync_task.done()
                    and asyncio.current_task() != self._channel_sync_task
                ):
                    self._channel_sync_task.cancel()
                    self._channel_sync_task = None
                try:
                    loop = asyncio.get_running_loop()
                    self._channel_sync_task = loop.create_task(self._deferred_channel_sync())
                except RuntimeError:
                    pass
                if self._brightness is None:
                    self._brightness = 255
            await self.trigger_entity_update()
            return

        if cmd == CMD_EVENT_LIGHT_TIMER_END:
            if self._last_notification_cmd == CMD_EVENT_LIGHT_TIMER_END and not self._light_on:
                LOGGER.debug("Ignoring duplicate 0xEB burst notification")
                return
            self._last_notification_cmd = CMD_EVENT_LIGHT_TIMER_END
            LOGGER.debug("Received daylight timer end event 0xEB - turning off daylight")
            self._light_on = False
            self._is_on = bool(self._light_on or self._color_on)
            await self.trigger_entity_update()
            return

        if cmd == CMD_EVENT_MOONLIGHT_TIMER_END:
            if self._last_notification_cmd == CMD_EVENT_MOONLIGHT_TIMER_END and not self._color_on:
                LOGGER.debug("Ignoring duplicate 0xEC burst notification")
                return
            self._last_notification_cmd = CMD_EVENT_MOONLIGHT_TIMER_END
            LOGGER.debug("Received moodlight timer end event 0xEC - turning off moodlight")
            self._color_on = False
            self._is_on = bool(self._light_on or self._color_on)
            await self.trigger_entity_update()
            return

        self._last_notification_cmd = cmd

        if cmd == CMD_PERMISSION_RESPONSE:
            perm = data[IDX_CHANNEL] if len(data) > IDX_CHANNEL else None
            LOGGER.debug("Received device permission response 0xF0: %s (2=granted)", perm)
            return

        if cmd == CMD_STATUS_RESPONSE and self._status_response_event is not None:
            self._status_response_event.set()

        # Short ACK packets for non-status commands (e.g. write confirmations)
        if is_packet and cmd != CMD_STATUS_RESPONSE and payload_len <= 4:
            LOGGER.debug(
                "Received short ACK/notification (cmd=0x%02X, payload_len=%d, data=%s) - not updating state",
                cmd,
                payload_len,
                "".join(format(x, " 02x") for x in data[IDX_OPCODE:]),
            )
            return

        if len(data) <= IDX_CHANNEL:
            return

        channel = data[IDX_CHANNEL]
        if channel == CHANNEL_WHITE:
            if len(data) <= IDX_STATE:
                return
            self._light_on = data[IDX_STATE] == 1
            if data[IDX_STATE] == 1:
                self._hardware_mode = False
                self._brightness = (
                    int(data[IDX_BRIGHTNESS] * 255 / 100) if len(data) > IDX_BRIGHTNESS and data[IDX_BRIGHTNESS] > 0 else None
                )
                self._mode = ColorMode.WHITE
                self._color_on = False
            self._is_on = bool(self._light_on or self._color_on)
            LOGGER.debug(
                "White status: is_on=%s, light_on=%s, brightness=%s",
                self._is_on,
                self._light_on,
                self._brightness,
            )
            if not self._status_lock.locked():
                await self.trigger_entity_update()
        elif channel == CHANNEL_COLOR:
            if len(data) <= IDX_STATE:
                return
            self._color_on = data[IDX_STATE] == 1
            if data[IDX_STATE] == 1:
                self._hardware_mode = False
                self._mode = ColorMode.RGB
                self._light_on = False
                if len(data) > IDX_SCENE and data[IDX_SCENE] < len(self._supported_effects):
                    self._effect = self._supported_effects[data[IDX_SCENE]]
                self._color_brightness = (
                    int(data[IDX_BRIGHTNESS] * 255 / 100) if len(data) > IDX_BRIGHTNESS and data[IDX_BRIGHTNESS] > 0 else None
                )
                if len(data) > IDX_BLUE:
                    self._rgb_color = (data[IDX_RED], data[IDX_GREEN], data[IDX_BLUE])
            self._is_on = bool(self._light_on or self._color_on)
            LOGGER.debug(
                "RGB status: is_on=%s, color_on=%s, brightness=%s, rgb color=%s, effect=%s",
                self._is_on,
                self._color_on,
                self._color_brightness,
                self._rgb_color,
                self._effect,
            )
            LOGGER.debug(
                "state: %s, light_on %s, color_on %s",
                data[IDX_STATE] if len(data) > IDX_STATE else None,
                self._light_on,
                self._color_on,
            )
            if not self._status_lock.locked():
                await self.trigger_entity_update()
        elif channel == CHANNEL_OFF:
            LOGGER.debug(
                "Received channel off (channel 255) for queried channel %s (hardware_mode=%s)",
                self._last_queried_channel,
                self._hardware_mode,
            )
            if self._hardware_mode:
                LOGGER.debug("In hardware mode; preserving state on channel 255 response")
            else:
                if self._last_queried_channel == CHANNEL_WHITE:
                    self._light_on = False
                elif self._last_queried_channel == CHANNEL_COLOR:
                    self._color_on = False
                else:
                    self._light_on = False
                    self._color_on = False
                self._is_on = bool(self._light_on or self._color_on)
                LOGGER.debug(
                    "Channel %s off (channel 255): is_on=%s, light_on=%s, color_on=%s",
                    self._last_queried_channel,
                    self._is_on,
                    self._light_on,
                    self._color_on,
                )
                if not self._status_lock.locked():
                    await self.trigger_entity_update()
        elif channel == CHANNEL_SHUTDOWN:
            LOGGER.debug("Device is going to shut down (channel 0)")
            self._hardware_mode = False
            self._is_on = False
            self._light_on = False
            self._color_on = False
            await self.trigger_entity_update()
        else:
            LOGGER.debug(
                "Received unknown notification channel %s (cmd=0x%02X, len=%d): %s",
                channel,
                cmd,
                len(data),
                "".join(format(x, " 02x") for x in data),
            )

    async def connect(self) -> bool:
        """Connect to device and set up notifications.

        Returns:
            True if connection was successful, False otherwise.
        """
        self._closing = False
        self._last_notification_cmd = None
        async with self._connect_lock:
            if self._device is not None and self._device.is_connected and self._write_uuid is not None:
                return True

            LOGGER.debug("Going to connect to device")
            try:
                if HAVE_BLEAK_RETRY_CONNECTOR:
                    self._device = await establish_connection(
                        BleakClientWithServiceCache,
                        self._ble_device,
                        name=self._mac,
                        disconnected_callback=self.disconnected_callback,
                        max_attempts=3,
                        use_services_cache=False,
                    )
                else:
                    if self._device is None:
                        self._device = BleakClient(self._ble_device, disconnected_callback=self.disconnected_callback)
                    if not self._device.is_connected:
                        await self._device.connect(timeout=20)

                await asyncio.sleep(0.1)

                for char in self._device.services.characteristics.values():
                    char_uuid = char.uuid.lower()
                    if char_uuid in WRITE_CHARACTERISTIC_UUIDS:
                        self._write_uuid = char.uuid
                    if char_uuid in READ_CHARACTERISTIC_UUIDS:
                        self._read_uuid = char.uuid
                    if char_uuid in VERSION_CHARACTERISTIC_UUIDS:
                        self._version_uuid = char.uuid

                if not self._read_uuid or not self._write_uuid:
                    LOGGER.error("No supported read/write UUIDs found")
                    return False

                LOGGER.info("Read UUID: %s, Write UUID: %s", self._read_uuid, self._write_uuid)

                await asyncio.sleep(0.1)
                LOGGER.info("Starting notifications")

                await self._device.start_notify(self._read_uuid, self.notification_handler)

                if self._version_uuid:
                    try:
                        version_bytes = await self._device.read_gatt_char(self._version_uuid)
                        self._firmware_version = version_bytes.decode("utf-8", errors="replace").strip("\x00 \t\r\n")
                        LOGGER.info("Firmware version: %s", self._firmware_version)
                        await self.trigger_entity_update()
                    except Exception as error:  # noqa: BLE001
                        LOGGER.debug("Could not read firmware version: %s", error)
                else:
                    LOGGER.debug(
                        "No standard firmware version characteristic found on device (discovered: %s)",
                        [char.uuid for char in self._device.services.characteristics.values()],
                    )
            except Exception as error:  # noqa: BLE001
                track = traceback.format_exc()
                if "already shutdown" in str(error).lower() or self._closing:
                    LOGGER.debug("Connection aborted during shutdown: %s", error)
                else:
                    LOGGER.debug(track)
                    LOGGER.error("Error connecting: %s", error)
                await self.disconnect()
                return False

        if (
            self._reconnect_task is not None
            and not self._reconnect_task.done()
            and asyncio.current_task() != self._reconnect_task
        ):
            self._reconnect_task.cancel()
            self._reconnect_task = None
        return True

    async def update(self) -> None:
        """Refresh device status if connected, or trigger reconnect."""
        if not self.is_connected:
            LOGGER.debug("Device is not connected, scheduling reconnect and skipping status update")
            self.trigger_reconnect()
            return

        try:
            LOGGER.info("Triggering update")
            await self.triggerStatus()

        except Exception as error:  # noqa: BLE001
            track = traceback.format_exc()
            LOGGER.debug(track)
            LOGGER.error("Error getting status: %s", error)
            await self.disconnect()

    async def disconnect(self, closing: bool = False) -> None:
        """Disconnect from device and mark entity as off.

        Args:
            closing: If True, mark instance as permanently closing/shutting down.
        """
        LOGGER.debug("Disconnecting (closing=%s)", closing)
        if closing:
            self._closing = True
        self._cancel_channel_sync()
        if (
            self._reconnect_task is not None
            and not self._reconnect_task.done()
            and asyncio.current_task() != self._reconnect_task
        ):
            self._reconnect_task.cancel()
            self._reconnect_task = None
        client = self._device
        read_uuid = self._read_uuid
        self._device = None
        self._write_uuid = None
        self._read_uuid = None
        self._version_uuid = None
        self._last_notification_cmd = None
        self._last_notification_data = None
        self._last_notification_time = 0.0
        self._hardware_mode = False
        self._last_queried_channel = None
        self._is_on = False
        self._light_on = False
        self._color_on = False
        if client is not None:
            try:
                if read_uuid is not None and client.is_connected:
                    try:
                        await client.stop_notify(read_uuid)
                    except Exception as error:  # noqa: BLE001
                        LOGGER.debug("Error while stopping notifications: %s", error)
                if client.is_connected:
                    await client.disconnect()
            except Exception as error:  # noqa: BLE001
                LOGGER.debug("Error while disconnecting: %s", error)
        await self.trigger_entity_update()
