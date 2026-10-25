"""Constants for the Beurer BLE integration."""

from __future__ import annotations

import logging
from enum import IntEnum
from typing import Final

LOGGER: logging.Logger = logging.getLogger("custom_components.beurer")
DOMAIN: Final = "beurer"

# Bluetooth GATT UUIDs
SERVICE_UUID: Final = "14839ac4-7d7e-415c-9a42-167340cf2339"
WRITE_CHARACTERISTIC_UUID: Final = "8b00ace7-eb0b-49b0-bbe9-9aee0a26e1a3"
NOTIFY_CHARACTERISTIC_UUID: Final = "0734594a-a8e7-4b1a-a6b1-cd5243059a57"

# Standard Bluetooth Device Information Service UUIDs
VERSION_SERVICE_UUID: Final = "0000180a-0000-1000-8000-00805f9b34fb"
VERSION_CHARACTERISTIC_UUID_SOFTWARE: Final = "00002a28-0000-1000-8000-00805f9b34fb"
VERSION_CHARACTERISTIC_UUID_FIRMWARE: Final = "00002a26-0000-1000-8000-00805f9b34fb"

WRITE_CHARACTERISTIC_UUIDS: Final[set[str]] = {WRITE_CHARACTERISTIC_UUID}
READ_CHARACTERISTIC_UUIDS: Final[set[str]] = {NOTIFY_CHARACTERISTIC_UUID}
VERSION_CHARACTERISTIC_UUIDS: Final[set[str]] = {
    VERSION_CHARACTERISTIC_UUID_SOFTWARE,
    "00002a28",
    "2a28",
    VERSION_CHARACTERISTIC_UUID_FIRMWARE,
    "00002a26",
    "2a26",
}

# Packet Framing Markers
PACKET_HEADER: Final[list[int]] = [0xFE, 0xEF]
PACKET_TYPE_COMMAND: Final = 0x0A
PACKET_TYPE_NOTIFICATION: Final = 0x0C
PACKET_SYNC_COMMAND: Final[list[int]] = [0xAB, 0xAA]
PACKET_SYNC_NOTIFICATION: Final[list[int]] = [0xAB, 0xBB]
PACKET_FOOTER: Final[list[int]] = [0x55, 0x0D, 0x0A]


class PacketIndex(IntEnum):
    """Indices within incoming notification packets."""

    HEADER_0 = 0
    HEADER_1 = 1
    PACKET_TYPE = 2
    TOTAL_LEN = 3
    SYNC_0 = 4
    SYNC_1 = 5
    PAYLOAD_LEN = 6
    OPCODE = 7
    CHANNEL = 8
    STATE = 9
    BRIGHTNESS = 10
    TIMER_ACTIVE = 11
    TIMER_MINUTES = 12
    RED = 13
    GREEN = 14
    BLUE = 15
    SCENE = 16


IDX_HEADER_0: Final = PacketIndex.HEADER_0
IDX_HEADER_1: Final = PacketIndex.HEADER_1
IDX_PACKET_TYPE: Final = PacketIndex.PACKET_TYPE
IDX_TOTAL_LEN: Final = PacketIndex.TOTAL_LEN
IDX_SYNC_0: Final = PacketIndex.SYNC_0
IDX_SYNC_1: Final = PacketIndex.SYNC_1
IDX_PAYLOAD_LEN: Final = PacketIndex.PAYLOAD_LEN
IDX_OPCODE: Final = PacketIndex.OPCODE
IDX_CHANNEL: Final = PacketIndex.CHANNEL
IDX_STATE: Final = PacketIndex.STATE
IDX_BRIGHTNESS: Final = PacketIndex.BRIGHTNESS
IDX_TIMER_ACTIVE: Final = PacketIndex.TIMER_ACTIVE
IDX_TIMER_MINUTES: Final = PacketIndex.TIMER_MINUTES
IDX_RED: Final = PacketIndex.RED
IDX_GREEN: Final = PacketIndex.GREEN
IDX_BLUE: Final = PacketIndex.BLUE
IDX_SCENE: Final = PacketIndex.SCENE


class Channel(IntEnum):
    """Protocol lighting channels and response subcodes."""

    SHUTDOWN = 0x00
    WHITE = 0x01
    COLOR = 0x02
    OFF = 0xFF


CHANNEL_SHUTDOWN: Final = Channel.SHUTDOWN
CHANNEL_WHITE: Final = Channel.WHITE
CHANNEL_COLOR: Final = Channel.COLOR
CHANNEL_OFF: Final = Channel.OFF

# Protocol Request Opcodes (Client -> Device)
CMD_REQUEST_PERMISSION: Final = 0x00
CMD_QUERY_STATUS: Final = 0x30
CMD_SET_BRIGHTNESS: Final = 0x31
CMD_SET_COLOR: Final = 0x32
CMD_SET_TIMER_DURATION: Final = 0x33
CMD_SET_EFFECT: Final = 0x34
CMD_DISABLE_CHANNEL: Final = 0x35
CMD_DISABLE_TIMER: Final = 0x36
CMD_ENABLE_CHANNEL: Final = 0x37
CMD_ENABLE_TIMER: Final = 0x38

# Protocol Response / Event Opcodes (Device -> Client)
CMD_STATUS_RESPONSE: Final = 0xD0
CMD_EVENT_SHUTDOWN: Final = 0xE8
CMD_EVENT_LIGHT_TIMER_END: Final = 0xEB
CMD_EVENT_MOONLIGHT_TIMER_END: Final = 0xEC
CMD_PERMISSION_RESPONSE: Final = 0xF0

# Supported moodlight effects
EFFECTS: Final[list[str]] = [
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

# Hardware countdown timer limits in minutes
MIN_TIMER_DURATION: Final = 1
MAX_TIMER_DURATION: Final = 120
DEFAULT_TIMER_DURATION: Final = 15
