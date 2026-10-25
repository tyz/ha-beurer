"""Platform for number integration with Beurer TL 100."""

from __future__ import annotations

from collections.abc import Callable
from typing import override

from bleak.exc import BleakError
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import BeurerConfigEntry
from .beurer import BeurerCommunicationError, BeurerInstance
from .const import DOMAIN, LOGGER, MAX_TIMER_DURATION, MIN_TIMER_DURATION


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BeurerConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Beurer number platform from a config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Config entry containing device details.
        async_add_entities: Callback to register entities with HA.
    """
    LOGGER.debug("Setting up number platform for Beurer")
    instance: BeurerInstance = config_entry.runtime_data
    async_add_entities([BeurerTimerDurationNumber(instance, config_entry.data["name"], config_entry.entry_id)])


class BeurerTimerDurationNumber(NumberEntity):
    """Representation of the Beurer countdown timer duration setting."""

    _attr_has_entity_name = True
    _attr_translation_key = "timer_duration"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = float(MIN_TIMER_DURATION)
    _attr_native_max_value = float(MAX_TIMER_DURATION)
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    _attr_should_poll = False

    def __init__(self, beurer_instance: BeurerInstance, name: str, entry_id: str) -> None:
        """Initialize the Beurer countdown duration entity.

        Args:
            beurer_instance: Controller instance for the physical lamp.
            name: Friendly display name for the device.
            entry_id: Config entry unique identifier.
        """
        self._instance: BeurerInstance = beurer_instance
        self._name: str = name
        self._entry_id: str = entry_id
        self._attr_unique_id: str = f"{self._instance.mac}_timer_duration"
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
    def native_value(self) -> float:
        """Return the current timer duration in minutes."""
        return float(self._instance.timer_duration)

    @override
    async def async_set_native_value(self, value: float) -> None:
        """Set the hardware timer duration in minutes.

        Args:
            value: Desired countdown duration (1 to 120).

        Raises:
            HomeAssistantError: If communication with the device fails.
        """
        try:
            await self._instance.set_timer_duration(int(value))
        except (BeurerCommunicationError, BleakError, TimeoutError, OSError) as err:
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
