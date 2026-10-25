# Beurer TL 100 Bluetooth LE Protocol Specification

This document details the low-level Bluetooth Low Energy (BLE) protocol used by the Beurer TL 100 daylight lamp (and compatible models such as the WL 90 and WL 75).

## 1. GATT Services & Characteristics

The device advertises with the name prefix `TL100` (or `TL 100`) and exposes the following custom vendor GATT service:

| Name | UUID | Properties | Description |
|---|---|---|---|
| **Service** | `14839AC4-7D7E-415C-9A42-167340CF2339` | Primary Service | Main control service |
| **Write Characteristic** | `8B00ACE7-EB0B-49B0-BBE9-9AEE0A26E1A3` | Write / Write Without Response | Commands from client to lamp |
| **Notify Characteristic** | `0734594A-A8E7-4B1A-A6B1-CD5243059A57` | Notify / Read | Status notifications and spontaneous events from lamp |

### 1.1 Device Information & Firmware Revision

- **WL 75**: Exposes the standard Bluetooth Device Information Service (`0000180A-0000-1000-8000-00805F9B34FB`) and Software Revision characteristic (`00002A28-0000-1000-8000-00805F9B34FB`), which the official Beurer LightUp app reads upon connection.
- **TL 100**: Does **not** expose the Device Information Service (`0x180A`) or revision characteristics (`0x2A28` / `0x2A26`), nor any proprietary protocol command to query firmware version. The official Beurer LightUp app does not query or display firmware version for the TL 100. Its GATT table exposes only the vendor service above, vendor auxiliary characteristics (`BA04C4B2-...`, `E06D5EFB-...`), and the Telink OTA update service (`00010203-0405-0607-0809-0A0B0C0D2B12`).

---

## 2. Packet Framing & Checksum

All communication packets sent to or received from the lamp are encapsulated in a fixed framing structure with sync markers and a checksum.

### 2.1 Outgoing Packet Structure (Client -> Lamp)
Outgoing command packets follow an 11-byte overhead framing:

```
[0xFE, 0xEF, 0x0A, (payload_len + 7), 0xAB, 0xAA, (payload_len + 2)] + [PAYLOAD] + [CHECKSUM, 0x55, 0x0D, 0x0A]
```

- `Header`: `0xFE, 0xEF, 0x0A`
- `Packet Length Byte`: `payload_len + 7` (length of packet from byte 3 through checksum)
- `Sync Markers`: `0xAB, 0xAA`
- `Payload Length Byte`: `payload_len + 2`
- `Payload`: 1 to 4 command bytes (starts with the command opcode)
- `Checksum`: XOR checksum calculated over `PAYLOAD`:
  - Initial accumulator: `payload_len + 2`
  - XOR accumulated with each byte in `PAYLOAD`
- `Footer`: `0x55, 0x0D, 0x0A` (`\r\n`)

### 2.2 Incoming Notification Structure (Lamp -> Client)
Notifications arrive with the following structure:

```
[0xFE, 0xEF, 0x0C, total_len, 0xAB, 0xBB, (payload_len + 2)] + [PAYLOAD] + [CHECKSUM, 0x55, 0x0D, 0x0A]
```

- Byte 0..1: `0xFE, 0xEF` (Magic header)
- Byte 2: `0x0C` (Incoming notification indicator)
- Byte 4..5: `0xAB, 0xBB` (Incoming sync markers)
- Byte 6: Length of payload + 2
- Byte 7+: Payload bytes (starts with response opcode)
- End: Checksum byte followed by `0x55, 0x0D, 0x0A`

> **Note on receiving.** Incoming frames are checked for framing: a frame whose
> declared payload length runs past the bytes actually received is discarded
> entirely, because parsing it would index into whatever follows and could apply
> a state the lamp never reported. The checksum is computed and mismatches are
> logged at debug level, but the frame is still processed. BLE already carries a
> link-layer CRC, and no capture of a TL 100 status response has been verified to
> use the same XOR convention as the outgoing frames (the decoded LightUp app
> does not calculate a checksum for this device at all), so rejecting on mismatch
> risks silently discarding valid state. The log line exists to make protocol
> drift visible.

---

## 3. Channels

The lamp has two independent lighting subsystems (channels):
- **Channel `0x01` (Daylight / White)**: High-power daylight LED array supporting brightness from 1% to 100%.
- **Channel `0x02` (Moodlight / RGB)**: RGB color LEDs supporting solid 24-bit RGB colors (0–255 per component), brightness (1–100%), and 10 dynamic color scenes.

---

## 4. Command Set (Client -> Lamp)

All payloads below are wrapped in the framing described in section 2.1.

| Opcode | Payload Bytes | Description |
|---|---|---|
| `0x00` | `[0x00, 0x02]` | **Request Permission / Handshake**: Returns `0xF0, 0x02` on success. |
| `0x30` | `[0x30, channel]` | **Query Channel Status**: Requests status for Channel `0x01` (White) or `0x02` (RGB). |
| `0x31` | `[0x31, channel, brightness]` | **Set Brightness**: Brightness percentage from `0x01` to `0x64` (1–100%). |
| `0x32` | `[0x32, R, G, B]` | **Set RGB Color**: Red, Green, Blue bytes (`0x00` to `0xFF`). Automatically switches channel 2 on. |
| `0x33` | `[0x33, channel, minutes]` | **Set Timer Duration**: Sets automatic off-timer duration in minutes (`0x01` to `0x78` = 1–120 minutes). Values above 120 minutes default to 120 minutes on hardware. |
| `0x34` | `[0x34, scene_index]` | **Set Scene / Effect**: Selects moodlight dynamic effect (`0x00` to `0x0A`). |
| `0x35` | `[0x35, channel]` | **Disable Channel**: Turns off Channel `0x01` (White) or `0x02` (RGB). |
| `0x36` | `[0x36, channel]` | **Disable Timer**: Cancels the active off-timer on specified channel. |
| `0x37` | `[0x37, channel]` | **Enable Channel**: Turns on Channel `0x01` (White) or `0x02` (RGB). |
| `0x38` | `[0x38, channel]` | **Enable Timer**: Activates countdown timer for specified channel. Must only be sent when the channel is ON. |

> **Firmware Note on 100% Daylight Brightness**: Setting white brightness to 100% (`[0x31, 0x01, 0x64]`) on some firmware versions triggers an internal bug that flips the lamp to red RGB mode. Capping daylight brightness at 99% (`0x63`) reliably works around this issue.

> **Firmware Note on Timer Commands while Off**: Sending `0x38` (Enable Timer) or `0x33` (Set Timer Duration) when the lamp is turned off causes the hardware microcontroller to hang and become unresponsive until power-cycled. Timer commands must only be dispatched while the target channel / lamp is active (turned on). Canceling or changing timer settings should avoid BLE packet transmission when the lamp is off.

> **Firmware Note on Timer Enable vs Duration Sequencing**: Sending `0x38` (Enable Timer) initializes the hardware countdown timer to its default duration of 120 minutes. When enabling the countdown timer with a specific duration (e.g., 7, 15, 30, 45, or 90 minutes), `0x38` must always be transmitted before `0x33`. Transmitting `0x33` before `0x38` causes the microcontroller to immediately overwrite the chosen duration back to 120 minutes.

---

## 5. Status & Asynchronous Notifications (Lamp -> Client)

The lamp sends notifications for queries and spontaneous physical interactions:

### 5.1 Status Response (`0xD0` / `RESPONSE_DEVICE_LIGHT`)
Returned in response to `0x30` query or after parameter adjustments:

- `res[7]` = `0xD0` (Response opcode)
- `res[8]` = **Channel Type / Subcode**:
  - `0x01`: White / Daylight full status packet:
    - `res[9]` = **State**: `0x01` = Enabled / ON, `0x00` = Disabled / OFF
    - `res[10]` = **Brightness**: Percentage `1` to `100` (or `0` when off)
    - `res[11]` = **Timer Active**: `0x01` = Active, `0x00` = Inactive
    - `res[12]` = **Timer Minutes Remaining**: `0` to `120` minutes
  - `0x02`: Moodlight / RGB full status packet:
    - `res[9]` = **State**: `0x01` = Enabled / ON, `0x00` = Disabled / OFF
    - `res[10]` = **Brightness**: Percentage `1` to `100`
    - `res[11]` = **Timer Active**: `0x01` = Active, `0x00` = Inactive
    - `res[12]` = **Timer Minutes Remaining**: `0` to `120` minutes
    - `res[13]` = **Red**: `0` to `255`
    - `res[14]` = **Green**: `0` to `255`
    - `res[15]` = **Blue**: `0` to `255`
    - `res[16]` = **Scene Index**: `0` to `10`
  - `0xFF`: Empty / hardware-mode ACK (`04 D0 FF`). Sent when querying a channel that is inactive over BLE or when the lamp is operating under standalone hardware MCU control (e.g. after being toggled via physical buttons). Contains no channel state data beyond `0xD0 0xFF`. Clients should treat this response as an empty acknowledgment that preserves existing state, rather than forcing channels off or overwriting active states.

### 5.2 Device Events

| Opcode | Event | Meaning & Expected Handling |
|---|---|---|
| `0xE8` | `TL100_DEVICE_SHUTDOWN` | Broadcast when physical power/toggle button is pressed (emitted in bursts of up to 5 duplicate packets). Toggles lamp power state. When turning off physically, the device drops the BLE connection shortly after. When turning on physically, the device operates in hardware mode and may restart its BLE stack within ~2 seconds; clients must handle this as a local state toggle without sending GATT writes (such as `0x37 0x01`), to prevent MCU freeze or conflicts. |
| `0xEB` | `RESPONSE_LIGHT_TIMER_END` | Daylight hardware timer set via BLE has elapsed; daylight channel turned off automatically. Clients should turn off daylight mode in state. |
| `0xEC` | `RESPONSE_MOONLIGHT_TIMER_END` | Moodlight hardware timer set via BLE has elapsed; moodlight channel turned off automatically. Clients should turn off moodlight mode in state. |
| `0xF0` | `RESPONSE_DEVICE_PERMISSION` | Permission response (`res[8] == 0x02` indicates control permission granted). |

> **Duplicate Packet Suppression**: The lamp repeats `0xE8`, `0xEB` and `0xEC` events several times within a few milliseconds (bursts of up to five identical packets are observed). A client that acts on every copy would toggle the light on and off repeatedly. Implementations should therefore drop a notification whose bytes are identical to the previous one when it arrives within a short window; this integration uses 0.3 s (`NOTIFICATION_DUPLICATE_WINDOW`).
>
> The window compares the whole packet, so it applies to every notification, `0xD0` status responses included. That is safe in practice because the lamp only repeats a status packet when the state it reports has not changed, and because the next *different* notification resets the comparison.

---

## 6. Moodlight Scenes / Effects

The device supports 11 predefined scenes on Channel 2 (RGB):

| Index | Scene Name | Description |
|---|---|---|
| `0` | `Off` | Solid single color (effects disabled) |
| `1` | `Random` | Smooth transition through random colors |
| `2` | `Rainbow` | Standard rainbow color cycle |
| `3` | `Rainbow Slow` | Slow rainbow color cycle |
| `4` | `Fusion` | Soft blended transitions |
| `5` | `Pulse` | Pulsing rhythmic color changes |
| `6` | `Wave` | Wave-like flowing transition |
| `7` | `Chill` | Calming pastel shifts |
| `8` | `Action` | Fast, vibrant color shifts |
| `9` | `Forest` | Natural greens, ambers, and earth tones |
| `10` | `Summer` | Warm yellows, oranges, and reds |
