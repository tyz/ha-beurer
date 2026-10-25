"""Platform for sensor integration with Beurer TL 100."""

from __future__ import annotations

from collections.abc import Callable
from typing import override

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
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
    """Set up the Beurer sensor platform from a config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Config entry containing device details.
        async_add_entities: Callback to register entities with HA.
    """
    LOGGER.debug("Setting up sensor platform for Beurer")
    instance: BeurerInstance = config_entry.runtime_data
    async_add_entities([BeurerTimerRemainingSensor(instance, config_entry.data["name"], config_entry.entry_id)])


class BeurerTimerRemainingSensor(SensorEntity):
    """Representation of the Beurer countdown timer remaining minutes sensor."""

    _attr_has_entity_name = True
    _attr_translation_key = "timer_remaining"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, beurer_instance: BeurerInstance, name: str, entry_id: str) -> None:
        """Initialize the Beurer timer remaining sensor entity.

        Args:
            beurer_instance: Controller instance for the physical lamp.
            name: Friendly display name for the device.
            entry_id: Config entry unique identifier.
        """
        self._instance: BeurerInstance = beurer_instance
        self._name: str = name
        self._entry_id: str = entry_id
        self._attr_unique_id: str = f"{self._instance.mac}_timer_remaining"
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
    def native_value(self) -> int:
        """Return the remaining countdown time in minutes."""
        return self._instance.timer_minutes_remaining

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
