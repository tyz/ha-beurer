"""Diagnostics support for Beurer BLE integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant

from .beurer import BeurerInstance
from .const import DOMAIN

TO_REDACT = {CONF_MAC, "address", "unique_id"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return diagnostics for a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry for which diagnostics are requested.

    Returns:
        Dictionary containing redacted diagnostics data.
    """
    instance: BeurerInstance | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)

    device_data: dict[str, Any] = {}
    if instance is not None:
        device_data = {
            "mac": instance.mac,
            "is_connected": instance.is_connected,
            "firmware_version": instance.firmware_version,
            "is_on": instance.is_on,
            "light_on": instance._light_on,
            "color_on": instance._color_on,
            "color_mode": str(instance.color_mode) if instance.color_mode is not None else None,
            "white_brightness": instance.white_brightness,
            "color_brightness": instance.color_brightness,
            "rgb_color": instance.rgb_color,
            "effect": instance.effect,
            "supported_effects": instance.supported_effects,
            "timer_duration": instance.timer_duration,
            "timer_active": instance.timer_active,
            "timer_minutes_remaining": instance.timer_minutes_remaining,
            "last_notification_cmd": hex(instance._last_notification_cmd)
            if instance._last_notification_cmd is not None
            else None,
            "last_queried_channel": instance._last_queried_channel,
            "is_closing": instance.is_closing,
        }

    entry_data: dict[str, Any] = {
        "entry_id": entry.entry_id,
        "version": entry.version,
        "domain": entry.domain,
        "title": entry.title,
        "data": dict(entry.data),
    }

    return {
        "entry": async_redact_data(entry_data, TO_REDACT),
        "device": async_redact_data(device_data, TO_REDACT),
    }
