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

---

## Removal

1. In Home Assistant, go to **Settings** > **Devices & services**.
2. Find the **Beurer** integration entry.
3. Click the three dots icon (**⋮**) on the device card and select **Delete**.
4. Confirm deletion. The integration will automatically cancel active reconnection tasks, cleanly disconnect the BLE connection, and remove its light entity from Home Assistant.

---

## Supported Features

* **Daylight Therapy (White Mode)**: Full on/off and brightness control.
* **Moodlight (RGB Mode)**: Color picker, independent color brightness control, and scene selection.
* **Hardware Countdown Timer**: Built-in hardware timer control via `number` (duration: 1–120 min), `switch` (start/cancel), and `sensor` (remaining time) entities.
* **Hardware Timer-End Events (`0xEB` / `0xEC`)**: Immediate state updates when the lamp turns off after timer expiration.
* **Physical Controls**: State stays in sync when using the buttons on the lamp.
* **Bluetooth Proxy Compatibility**: Works with standard Linux Bluetooth adapters and ESPHome Bluetooth Proxies.

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
