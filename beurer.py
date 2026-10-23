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

from .const import LOGGER

try:
    from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

    HAVE_BLEAK_RETRY_CONNECTOR = True
except ImportError:
    HAVE_BLEAK_RETRY_CONNECTOR = False

WRITE_CHARACTERISTIC_UUIDS: set[str] = {"8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"}
READ_CHARACTERISTIC_UUIDS: set[str] = {"0734594a-a8e7-4b1a-a6b1-cd5243059a57"}


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
        self._last_status_trigger: float = 0.0
        self._reconnect_task: asyncio.Task[None] | None = None
        self._closing: bool = False
        self._mode: ColorMode | None = ColorMode.WHITE
        self._supported_effects: list[str] = [
            "Off",
            "Random",
            "Rainbow",
            "Rainbow Slow",
            "Fusion",
            "Pulse",
            "Wave",
            "Chill",
            "Action",
            "Forest",
            "Summer",
        ]

    def set_device(self, device: BLEDevice) -> None:
        """Update the underlying BLEDevice.

        Args:
            device: The new BLEDevice instance.
        """
        self._ble_device = device

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
        self._device = None
        self._write_uuid = None
        self._read_uuid = None
        if self._trigger_update:
            self._trigger_update()
        if self._reconnect_task is None or self._reconnect_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._reconnect_task = loop.create_task(self._auto_reconnect())
            except RuntimeError:
                pass

    async def _auto_reconnect(self) -> None:
        """Attempt to reconnect after a short delay following disconnection."""
        LOGGER.debug("Scheduling auto-reconnect in 1 second")
        await asyncio.sleep(1)
        if self._closing:
            return
        if self._device is not None and self._device.is_connected:
            return
        LOGGER.debug("Executing auto-reconnect")
        try:
            if await self.connect():
                await self.triggerStatus()
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
        packet = [0xFE, 0xEF, 0x0A, length + 7, 0xAB, 0xAA, length + 2] + message + [checksum, 0x55, 0x0D, 0x0A]
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
        if self._light_on:
            # Turn off white daylight channel when switching to color mode
            await self.sendPacket([0x35, 0x01])
            self._light_on = False
            await asyncio.sleep(0.1)
        if not self._color_on:
            await self.sendPacket([0x37, 0x02])
            self._color_on = True
            await asyncio.sleep(0.1)
        await self.sendPacket([0x32, r, g, b])
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
        if not self._color_on:
            await self.sendPacket([0x37, 0x02])
            self._color_on = True
            await asyncio.sleep(0.1)
        brightness_percent = max(0, min(100, int(brightness / 255 * 100)))
        await self.sendPacket([0x31, 0x02, brightness_percent])
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
        if self._color_on:
            # Turn off color mode channel when switching to white daylight
            await self.sendPacket([0x35, 0x02])
            self._color_on = False
            await asyncio.sleep(0.1)
        if not self._light_on:
            await self.sendPacket([0x37, 0x01])
            self._light_on = True
            await asyncio.sleep(0.1)
        intensity_percent = max(0, min(100, int(intensity / 255 * 100)))
        # Cap at 99% to work around firmware bug where 100% in white mode
        # causes the device to switch to red/RGB mode (Deadolus#11)
        if intensity_percent == 100:
            intensity_percent = 99
        await self.sendPacket([0x31, 0x01, intensity_percent])
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
        if self._light_on:
            # Turn off white daylight channel when switching to color mode
            await self.sendPacket([0x35, 0x01])
            self._light_on = False
            await asyncio.sleep(0.1)
        if not self._color_on:
            await self.sendPacket([0x37, 0x02])
            self._color_on = True
            await asyncio.sleep(0.1)
        await self.sendPacket([0x34, self.find_effect_position(effect)])
        self._effect = effect
        self._color_on = True
        self._is_on = True
        await self.trigger_entity_update()

    async def turn_on(self) -> None:
        """Turn on the light in the current or saved mode."""
        LOGGER.debug("Turning on")
        if self._device is None or not self._device.is_connected:
            await self.connect()
        if self._mode == ColorMode.RGB:
            await self.sendPacket([0x37, 0x02])
            self._color_on = True
            if self._effect and self._effect != "Off":
                await asyncio.sleep(0.1)
                await self.sendPacket([0x34, self.find_effect_position(self._effect)])
            elif self._rgb_color:
                await asyncio.sleep(0.1)
                await self.sendPacket([0x32, self._rgb_color[0], self._rgb_color[1], self._rgb_color[2]])
            if self._color_brightness is not None:
                await asyncio.sleep(0.1)
                brightness_percent = max(0, min(100, int(self._color_brightness / 255 * 100)))
                await self.sendPacket([0x31, 0x02, brightness_percent])
        else:
            self._mode = ColorMode.WHITE
            self._light_on = True
            if self._brightness is None:
                self._brightness = 255
            await self.sendPacket([0x37, 0x01])
            await asyncio.sleep(0.1)
            intensity_percent = max(0, min(99, int(self._brightness / 255 * 100)))
            await self.sendPacket([0x31, 0x01, intensity_percent])
        self._is_on = True
        await self.trigger_entity_update()

    async def turn_off(self) -> None:
        """Turn off both white and color channels."""
        LOGGER.debug("Turning off")
        await self.sendPacket([0x35, 0x01])
        await self.sendPacket([0x35, 0x02])
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
        now = time.monotonic()
        if not force and now - self._last_status_trigger < 2.0:
            LOGGER.debug("Skipping triggerStatus, called too recently")
            return
        self._last_status_trigger = now
        await self.sendPacket([0x30, 0x01])
        await asyncio.sleep(0.2)
        await self.sendPacket([0x30, 0x02])
        LOGGER.info("Triggered update")

    async def trigger_entity_update(self) -> None:
        """Notify the entity callback of a state change."""
        if self._trigger_update:
            LOGGER.debug("Triggering async update")
            self._trigger_update()
        else:
            LOGGER.warning("No async update function provided: %s", self._trigger_update)

    async def notification_handler(self, characteristic: BleakGATTCharacteristic, res: bytearray) -> None:
        """Handle incoming GATT notifications from the device.

        Args:
            characteristic: Characteristic that produced the notification.
            res: Notification payload bytes.
        """
        LOGGER.debug("Received notification: %s", "".join(format(x, " 03x") for x in res))
        if len(res) < 8:
            return

        is_packet = len(res) >= 6 and res[0] == 0xFE and res[1] == 0xEF
        payload_len = res[6] if is_packet else len(res) - 7
        cmd = res[7]

        if cmd == 0xE8:
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
            else:
                self._light_on = True
                self._mode = ColorMode.WHITE
                if self._brightness is None:
                    self._brightness = 255
            await self.trigger_entity_update()
            return

        if cmd == 0xF0:
            perm = res[8] if len(res) > 8 else None
            LOGGER.debug("Received device permission response 0xF0: %s (2=granted)", perm)
            return

        # Short ACK packets for non-status commands (e.g. write confirmations)
        if is_packet and cmd != 0xD0 and payload_len < 8:
            LOGGER.debug(
                "Received short ACK/notification (cmd=0x%02X, payload_len=%d, data=%s) - not updating state",
                cmd,
                payload_len,
                "".join(format(x, " 02x") for x in res[7:]),
            )
            return

        if len(res) < 9:
            return

        reply_version = res[8]
        LOGGER.debug("Reply version is %s", reply_version)
        if reply_version == 1:
            self._light_on = res[9] == 1
            if res[9] == 1:
                self._brightness = int(res[10] * 255 / 100) if len(res) > 10 and res[10] > 0 else None
                self._mode = ColorMode.WHITE
            self._is_on = bool(self._light_on or self._color_on)
            LOGGER.debug(
                "White status: is_on=%s, light_on=%s, brightness=%s",
                self._is_on,
                self._light_on,
                self._brightness,
            )
            await self.trigger_entity_update()
        elif reply_version == 2:
            self._color_on = res[9] == 1
            if res[9] == 1:
                self._mode = ColorMode.RGB
                if len(res) > 16 and res[16] < len(self._supported_effects):
                    self._effect = self._supported_effects[res[16]]
            self._color_brightness = int(res[10] * 255 / 100) if len(res) > 10 and res[10] > 0 else None
            if len(res) > 15:
                self._rgb_color = (res[13], res[14], res[15])
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
                "res: %s, light_on %s, color_on %s",
                res[9] if len(res) > 9 else None,
                self._light_on,
                self._color_on,
            )
            await self.trigger_entity_update()
        elif reply_version == 255:
            self._is_on = False
            self._light_on = False
            self._color_on = False
            LOGGER.debug("Device off (reply_version 255)")
            await self.trigger_entity_update()
        elif reply_version == 0:
            LOGGER.debug("Device is going to shut down (reply_version 0)")
            self._is_on = False
            self._light_on = False
            self._color_on = False
            await self.trigger_entity_update()
        else:
            LOGGER.debug(
                "Received unknown notification version %s (cmd=0x%02X, len=%d): %s",
                reply_version,
                cmd,
                len(res),
                "".join(format(x, " 02x") for x in res),
            )

    async def connect(self) -> bool:
        """Connect to device and set up notifications.

        Returns:
            True if connection was successful, False otherwise.
        """
        self._closing = False
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

                if not self._read_uuid or not self._write_uuid:
                    LOGGER.error("No supported read/write UUIDs found")
                    return False

                LOGGER.info("Read UUID: %s, Write UUID: %s", self._read_uuid, self._write_uuid)

                await asyncio.sleep(0.1)
                LOGGER.info("Starting notifications")

                await self._device.start_notify(self._read_uuid, self.notification_handler)
            except Exception as error:  # noqa: BLE001
                track = traceback.format_exc()
                LOGGER.debug(track)
                LOGGER.error("Error connecting: %s", error)
                await self.disconnect()
                return False

        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None
        return True

    async def update(self) -> None:
        """Connect if needed and refresh status."""
        try:
            if (self._device is None or not self._device.is_connected) and not await self.connect():
                LOGGER.info("Was not able to connect to device for updates")
                return

            LOGGER.info("Triggering update")
            await self.triggerStatus()

        except Exception as error:  # noqa: BLE001
            track = traceback.format_exc()
            LOGGER.debug(track)
            LOGGER.error("Error getting status: %s", error)
            await self.disconnect()

    async def disconnect(self) -> None:
        """Disconnect from device and mark entity as off."""
        LOGGER.debug("Disconnecting")
        self._closing = True
        if self._reconnect_task is not None and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._device is not None:
            try:
                if self._read_uuid is not None and self._device.is_connected:
                    try:
                        await self._device.stop_notify(self._read_uuid)
                    except Exception as error:  # noqa: BLE001
                        LOGGER.debug("Error while stopping notifications: %s", error)
                if self._device.is_connected:
                    await self._device.disconnect()
            except Exception as error:  # noqa: BLE001
                LOGGER.debug("Error while disconnecting: %s", error)
        self._device = None
        self._write_uuid = None
        self._read_uuid = None
        self._is_on = False
        self._light_on = False
        self._color_on = False
        await self.trigger_entity_update()
