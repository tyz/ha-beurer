"""Platform for switch integration with Beurer TL 100."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, override

from bleak.exc import BleakError
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BeurerConfigEntry
from .beurer import BeurerInstance
from .const import DOMAIN, LOGGER


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BeurerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Beurer switch platform from a config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Config entry containing device details.
        async_add_entities: Callback to register entities with HA.
    """
    LOGGER.debug("Setting up switch platform for Beurer")
    instance: BeurerInstance = config_entry.runtime_data
    async_add_entities([BeurerTimerSwitch(instance, config_entry.data["name"], config_entry.entry_id)])


class BeurerTimerSwitch(SwitchEntity):
    """Representation of the Beurer countdown timer switch."""

    _attr_has_entity_name = True
    _attr_translation_key = "timer"

    def __init__(self, beurer_instance: BeurerInstance, name: str, entry_id: str) -> None:
        """Initialize the Beurer timer switch entity.

        Args:
            beurer_instance: Controller instance for the physical lamp.
            name: Friendly display name for the device.
            entry_id: Config entry unique identifier.
        """
        self._instance: BeurerInstance = beurer_instance
        self._name: str = name
        self._entry_id: str = entry_id
        self._attr_unique_id: str = f"{self._instance.mac}_timer"
        self._unregister_callback: Callable[[], None] | None = None

    @override
    async def async_added_to_hass(self) -> None:
        """Register callbacks after being added to Home Assistant."""
        self._unregister_callback = self._instance.register_update_callback(self.async_write_ha_state)

    @override
    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed from Home Assistant."""
        if self._unregister_callback is not None:
            self._unregister_callback()
            self._unregister_callback = None

    @property
    @override
    def is_on(self) -> bool:
        """Return True if the countdown timer is running."""
        return self._instance.timer_active

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start/enable the countdown timer.

        Args:
            **kwargs: Unused extra arguments.

        Raises:
            HomeAssistantError: If communication fails or lamp is off.
        """
        if not self._instance.is_on:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="lamp_must_be_on",
            )
        try:
            await self._instance.enable_timer()
        except (BleakError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={
                    "name": self._name or self._instance.mac,
                    "error": str(err),
                },
            ) from err

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Cancel/disable the countdown timer.

        Args:
            **kwargs: Unused extra arguments.

        Raises:
            HomeAssistantError: If communication with the device fails.
        """
        try:
            await self._instance.disable_timer()
        except (BleakError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={
                    "name": self._name or self._instance.mac,
                    "error": str(err),
                },
            ) from err

    @property
    @override
    def available(self) -> bool:
        """Return True when the lamp can actually be controlled."""
        return self._instance.available

    @property
    @override
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self._instance.mac)},
            name=self._name,
            manufacturer="Beurer",
            model="TL 100",
        )
        if self._instance.firmware_version:
            info["sw_version"] = self._instance.firmware_version
        return info
