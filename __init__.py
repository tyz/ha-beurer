"""Beurer BLE daylight lamp integration for Home Assistant."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .beurer import BeurerInstance
from .const import DOMAIN, LOGGER

PLATFORMS: list[str] = ["light"]


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
        await instance.disconnect()
    return unload_ok
