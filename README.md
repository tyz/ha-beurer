# Beurer TL 100 for Home Assistant

A custom Home Assistant integration for controlling the **Beurer TL 100** daylight therapy and moodlight lamp (as well as compatible models like the WL 90 and WL 75) over Bluetooth Low Energy (BLE).

This repository is an actively maintained fork of [Deadolus/ha-beurer](https://github.com/Deadolus/ha-beurer), updated to meet modern Home Assistant architectural standards and resolve long-standing connection and protocol bugs.

---

## What's New & Fixed (vs. Deadolus's Version)

* **Modern Home Assistant Bluetooth Architecture**: Completely migrated to the standard Home Assistant Bluetooth subsystem (`homeassistant.components.bluetooth`) and `bleak-retry-connector`.
* **ESPHome Bluetooth Proxy & Multi-Adapter Support**: Uses BLE advertisement callbacks (`async_register_callback`) so the lamp seamlessly roams across ESPHome Bluetooth Proxies and local Bluetooth adapters without losing connection.
* **Physical Button State Synchronization**: Correctly handles hardware power button events (`0xE8`). When the lamp is turned on or off using its physical button, Home Assistant updates immediately and retains its state through subsequent BLE reconnections.
* **Decoupled Daylight and Moodlight Channels**: White daylight (channel 1) and RGB moodlight (channel 2) are fully decoupled. Turning on white light correctly disables color mode, and vice versa, matching the lamp's physical hardware behavior.
* **Fixed 100% White Brightness Firmware Bug**: The lamp firmware has a known bug where setting white brightness to 100% (`0x64`) causes an unintended red tint shift. The integration caps white brightness at 99% (`0x63`) under the hood, ensuring pure daylight output.
* **Independent Brightness & State Retention**: White daylight and RGB moodlight brightness levels are tracked and scaled independently (0–255 in Home Assistant, 1–100% on hardware).
* **Full Moodlight Scenes / Effects**: Support for all 11 built-in moodlight effect presets (Rainbow, Rainbow Slow, Pulse, Wave, Forest, Summer, etc.).
* **Hardware Countdown Timer Support**: Configurable countdown off-timer (1–120 minutes) exposed via dedicated Home Assistant `number`, `switch`, and `sensor` entities, with built-in safety preventing timer activation when the lamp is off.
* **Duplicate-Packet Suppression**: The lamp repeats button and timer events up to five times; identical notifications inside a 0.3 s window are collapsed so a single physical press is a single state change.
* **Reauthentication & Reconfiguration**: **Reconfigure** changes the MAC address or name in place, keeping entity IDs and automations intact, and the reauthentication flow re-validates a lamp whose address changed. A lamp that is only temporarily out of reach is retried automatically and shown as unavailable instead.
* **Honest Availability**: Entities are marked unavailable whenever no BLE connection exists, so a lamp that cannot be controlled never looks as if it can.
* **Hardware Timer-End Events**: Intercepts `0xEB` and `0xEC` BLE notifications to immediately update entity states when the lamp shuts off on timer completion.
* **Reliable Connection Management & Serialization**: BLE writes are serialized using asynchronous locks and status queries are debounced to prevent packet collision and connection drops.
* **Graceful Shutdown & Unload**: Properly cancels background reconnection tasks and disconnects cleanly when Home Assistant stops or the integration is reloaded.
* **Protocol Documentation**: Added a comprehensive BLE protocol specification in [`README.bluetooth.md`](README.bluetooth.md).
* **Automated Unit Tests**: Added a full test suite with mock fixtures covering BLE communication, state parsing, and Home Assistant entity lifecycles.

---

## Installation

### Method 1: HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed and configured in Home Assistant.
2. In Home Assistant, navigate to **HACS** > **Integrations**.
3. Click the three dots icon (**⋮**) in the top right corner and select **Custom repositories**.
4. Enter:
   * **Repository**: `https://github.com/tyz/ha-beurer`
   * **Type**: `Integration`
5. Click **Add**.
6. Search for **Beurer** in HACS and click **Download**.
7. Restart Home Assistant.

### Method 2: Manual Installation

1. Clone or download this repository.
2. Copy all files into your Home Assistant configuration directory under `custom_components/beurer/`:
   ```bash
   cd /config/custom_components
   git clone https://github.com/tyz/ha-beurer beurer
   ```
3. Restart Home Assistant.

---

## Configuration & Setup

1. In Home Assistant, go to **Settings** > **Devices & services**.
2. Click **Add integration** and search for **Beurer**.
3. The setup flow will automatically scan for nearby Beurer lamps advertising over BLE. Select your lamp from the list, or select **Configure manually** to enter the Bluetooth MAC address directly.
4. During setup, the integration will briefly toggle the lamp to confirm communication.
5. If you have multiple Beurer lamps, repeat the setup process for each device.

### Changing the address or name

If the lamp was factory reset, replaced, or renamed, open the integration entry, click **⋮** and choose **Reconfigure**. You can adjust the MAC address and the name; the entry and its entity IDs are preserved. The integration verifies the new address by blinking the lamp before saving it, and refuses an address that belongs to a different lamp.

### Reconnecting after the lamp becomes unreachable

While the lamp is unreachable its entities are reported as **unavailable**: it cannot be controlled, so Home Assistant does not pretend otherwise. The integration retries in the background and reconnects as soon as the lamp is reachable again — for example after you move it, after a Bluetooth proxy reboots, or after a power cut. The log shows a single line when the connection is lost and another when it returns, instead of one error per attempt.

If the lamp is gone for good (sold, broken, or reset to a different address), use **Reconfigure** to point the entry at its new address, or delete the integration entry.

---

## Removal

1. In Home Assistant, go to **Settings** > **Devices & services**.
2. Find the **Beurer** integration entry.
3. Click the three dots icon (**⋮**) on the device card and select **Delete**.
4. Confirm deletion. The integration will automatically cancel active reconnection tasks, cleanly disconnect the BLE connection, and remove its light entity from Home Assistant.

---

## Supported Features

* **Daylight Therapy (White Mode)**: Full on/off and brightness control.
* **Moodlight (RGB Mode)**: Color picker, independent color brightness control, and effect selection via the light entity's `effect` attribute.
* **Hardware Countdown Timer**: Built-in hardware timer control via `number` (duration: 1–120 min), `switch` (start/cancel), and `sensor` (remaining time) entities.
* **Hardware Timer-End Events (`0xEB` / `0xEC`)**: Immediate state updates when the lamp turns off after timer expiration.
* **Physical Controls**: State stays in sync when using the buttons on the lamp.
* **Bluetooth Proxy Compatibility**: Works with standard Linux Bluetooth adapters and ESPHome Bluetooth Proxies.

---

## Use Cases

* **Sunrise simulation for winter mornings**: schedule the daylight channel to brighten gradually with an automation that steps the brightness up over 20 minutes, so the room is already bright when the alarm goes off.
* **Light therapy sessions with a hard stop**: set the timer duration to your session length (for example 30 minutes) and turn the timer on. The lamp switches itself off when the session ends, and Home Assistant picks up the `0xEB` event immediately, so your dashboard stays accurate without polling.
* **Moodlight as an evening wind-down light**: switch to the RGB channel with one of the built-in effects and a low brightness, and use the hardware timer to make sure it does not burn all night.
* **Presence simulation while away**: turn the lamp on and off on a schedule through the countdown timer, which runs on the lamp itself and therefore keeps working even if Home Assistant or the network goes down.

---

## Examples

Turn on the daylight channel at 60% brightness for 20 minutes, then let the lamp switch itself off:

```yaml
automation:
  - alias: Morning light therapy
    triggers:
      - trigger: time
        at: "07:00:00"
    actions:
      - action: number.set_value
        target:
          entity_id: number.tl100_71ba_timer_duration
        data:
          value: 20
      - action: light.turn_on
        target:
          entity_id: light.tl100_71ba
        data:
          brightness_pct: 60
      - action: switch.turn_on
        target:
          entity_id: switch.tl100_71ba_timer
```

> The timer can only be started while the lamp is on. Turning the switch on while the lamp is off raises an error instead of locking up the firmware, so always turn the light on first.

Turn the timer off again when the session is cancelled early:

```yaml
actions:
  - action: switch.turn_off
    target:
      entity_id: switch.tl100_71ba_timer
```

Switch to the moodlight with the `Rainbow` effect:

```yaml
actions:
  - action: light.turn_on
    target:
      entity_id: light.tl100_71ba
    data:
      effect: Rainbow
      brightness_pct: 40
```

Entity IDs depend on the name you gave the lamp during setup; check **Developer tools** > **States** for the exact IDs.

---

## Known Limitations

* **Timer cannot be configured while the lamp is off**: the lamp firmware hangs when timer commands are sent to a channel that is off. The integration refuses these commands with an error rather than risking a lockup that needs a power cycle.
* **Daylight brightness is capped at 99%**: some firmware versions switch to a red-tinted RGB mode when white brightness is set to exactly 100%. The integration sends 99% instead, which is not visible in practice.
* **Timer duration must be set before enabling the timer**: the lamp initialises the countdown to 120 minutes whenever the timer is enabled. The integration always enables the timer before sending the duration, which keeps the value you chose.
* **One BLE connection at a time**: the lamp accepts a single connection, so the Beurer app on your phone cannot control it while Home Assistant is connected.
* **Firmware version is not reported on the TL 100**: the lamp does not expose the standard Device Information characteristic, so the firmware version stays empty in the device registry. Compatible models that do expose it are reported normally.
* **No separate `select` entity for moodlight effects**: the presets are exposed through the light entity's `effect` attribute, which is scriptable but does not appear as its own entity.

---

## Troubleshooting

### The lamp shows up as unavailable

Home Assistant only marks the entities as available while there is a live BLE connection. This happens when the lamp is out of reach, switched off at the wall, or the Bluetooth adapter or proxy is rebooting.

1. Check that the lamp has power and is within range of an adapter or proxy.
2. Wait up to a few seconds after powering it back on; the integration reconnects as soon as an advertisement arrives.
3. If it stays unavailable, verify the address under **Settings** > **Devices & services** > **Beurer TL 100** > **Reconfigure**.

### The lamp cannot be found during setup

The setup flow needs the lamp to advertise over Bluetooth Low Energy. Turn the lamp on, keep it close to an adapter, and retry. If it still does not appear, use **Configure manually** and enter the MAC address by hand.

### Reconfigure rejects my MAC address

Reconfigure refuses an address that belongs to a different lamp, to prevent accidentally pointing an existing entry at another device. If you really want to move the entry to a different lamp, delete the entry and set it up again.

### Everything is set up but commands fail

The lamp accepts only one BLE connection. Close the Beurer LightUp app on your phone, then retry. If the problem persists, enable debug logging (see below) and reproduce the failure.

### Collecting diagnostics for a bug report

The integration provides anonymised diagnostics that include the connection state, brightness and timer values, but no MAC address. In **Settings** > **Devices & services** > **Beurer TL 100**, click **⋮** and choose **Download diagnostics**.

---

## Debugging & Logs

To enable verbose debug logging for troubleshooting, add the following to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.beurer: debug
```

---

## Credits & History

* Forked and maintained by [Mathijs Maassen](https://github.com/tyz).
* Original integration by [Simon Egli (Deadolus)](https://github.com/Deadolus/ha-beurer). See [`README.Deadolus.md`](README.Deadolus.md) for the original documentation.
* Originally inspired by the [ha-triones](https://github.com/sysofwan/ha-triones) integration by sysofwan.
* Additional contributions from [@pyromaniac2k](https://github.com/pyromaniac2k) and [@ALandOfDodd](https://github.com/LandOfDodd).
