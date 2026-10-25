"""Beurer BLE daylight lamp integration for Home Assistant."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .beurer import BeurerInstance
from .const import DOMAIN, LOGGER

PLATFORMS: list[Platform] = [
    Platform.LIGHT,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beurer from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: The integration config entry.

    Returns:
        True if setup was successful.

    Raises:
        ConfigEntryNotReady: If the BLE device cannot be found.
    """
    LOGGER.debug("Setting up device from __init__")
    address: str = entry.data[CONF_MAC]
    device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if device is None:
        raise ConfigEntryNotReady(f"Was not able to find device with mac {address}")

    instance = BeurerInstance(device)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = instance

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update BLE device reference from Bluetooth advertisement."""
        mfr_data = service_info.manufacturer_data if isinstance(service_info.manufacturer_data, dict) else {}
        svc_data = service_info.service_data if isinstance(service_info.service_data, dict) else {}
        LOGGER.debug(
            "BLE advertisement from %s: name=%s, RSSI=%s, mfr_data=%s, service_data=%s, uuids=%s",
            getattr(service_info, "address", None),
            getattr(service_info, "name", None),
            getattr(service_info, "rssi", None),
            {k: v.hex() if isinstance(v, (bytes, bytearray)) else v for k, v in mfr_data.items()},
            {k: v.hex() if isinstance(v, (bytes, bytearray)) else v for k, v in svc_data.items()},
            getattr(service_info, "service_uuids", None),
        )
        instance.set_device(service_info.device)
        if not instance.is_connected and not instance.is_closing:
            instance.trigger_reconnect()

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            bluetooth.BluetoothCallbackMatcher(
                address=address,
            ),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    @callback
    def _async_unavailable(service_info: bluetooth.BluetoothServiceInfoBleak) -> None:
        """Handle device becoming unavailable due to lost BLE advertisements."""
        LOGGER.debug("BLE advertisements timed out for %s", address)
        hass.async_create_task(instance.trigger_entity_update())

    entry.async_on_unload(
        bluetooth.async_track_unavailable(
            hass,
            _async_unavailable,
            address,
            connectable=True,
        )
    )

    async def _async_stop(event: Event) -> None:
        """Close connection on Home Assistant stop."""
        await instance.disconnect(closing=True)

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance.
        entry: The integration config entry.

    Returns:
        True if unload was successful.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        instance: BeurerInstance = hass.data[DOMAIN].pop(entry.entry_id)
        await instance.disconnect(closing=True)
    return unload_ok
