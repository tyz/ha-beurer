"""Platform for light integration with Beurer TL 100."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import voluptuous as vol
from bleak import BleakError
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_MODE,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_WHITE,
    PLATFORM_SCHEMA,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import match_max_scale

from . import BeurerConfigEntry
from .beurer import BeurerInstance
from .const import DOMAIN, LOGGER

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({vol.Required(CONF_MAC): cv.string})
SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: BeurerConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Set up the Beurer light platform from a config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Config entry containing device details.
        async_add_devices: Callback to register entities with HA.
    """
    LOGGER.debug("Setting up device from light")
    instance: BeurerInstance = config_entry.runtime_data
    async_add_devices([BeurerLight(instance, config_entry.data["name"], config_entry.entry_id)])


class BeurerLight(LightEntity):
    """Representation of a Beurer daylight therapy light."""

    def __init__(self, beurerInstance: BeurerInstance, name: str, entry_id: str) -> None:
        """Initialize the BeurerLight.

        Args:
            beurerInstance: Controller instance for the physical lamp.
            name: Friendly display name for the entity.
            entry_id: Config entry unique identifier.
        """
        self._instance: BeurerInstance = beurerInstance
        self._entry_id: str = entry_id
        self._attr_supported_color_modes: set[ColorMode] = {ColorMode.RGB, ColorMode.WHITE}
        self._attr_name: str = name
        self._attr_unique_id: str = self._instance.mac
        self._unregister_callback: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Register callbacks after being added to Home Assistant."""
        self._instance.set_update_callback(self.update_callback)
        self._unregister_callback = self._instance.register_update_callback(self.update_callback)
        self._async_update_device_info()
        if not self._instance.is_connected:
            self._instance.trigger_reconnect()
        else:
            await self._instance.update()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister callback when entity is removed from Home Assistant."""
        if self._unregister_callback is not None:
            self._unregister_callback()
            self._unregister_callback = None

    def update_callback(self) -> None:
        """Write updated state to Home Assistant state machine."""
        self._async_update_device_info()
        self.async_write_ha_state()

    def _async_update_device_info(self) -> None:
        """Update device registry if firmware version is now known."""
        if not self.hass or not self._instance.firmware_version:
            return
        dev_reg = dr.async_get(self.hass)
        device_entry = dev_reg.async_get_device(identifiers={(DOMAIN, self._instance.mac)})
        if device_entry:
            if device_entry.sw_version != self._instance.firmware_version:
                dev_reg.async_update_device(
                    device_entry.id,
                    sw_version=self._instance.firmware_version,
                )
        else:
            dev_reg.async_get_or_create(
                config_entry_id=self._entry_id,
                identifiers={(DOMAIN, self._instance.mac)},
                manufacturer="Beurer",
                model="TL 100",
                name=self.name,
                sw_version=self._instance.firmware_version,
            )

    @property
    def available(self) -> bool:
        """Return True when the lamp can actually be controlled."""
        return self._instance.available

    @property
    def should_poll(self) -> bool:
        """Return True to poll as a fallback for offline/missed state updates."""
        return True

    @property
    def brightness(self) -> int | None:
        """Return current brightness depending on active color mode."""
        if self._instance.color_mode == ColorMode.WHITE:
            return self._instance.white_brightness
        return self._instance.color_brightness

    @property
    def is_on(self) -> bool | None:
        """Return True if light is currently turned on."""
        return self._instance.is_on

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return the current RGB color tuple scaled to maximum intensity or white in white mode."""
        if self._instance.color_mode == ColorMode.WHITE:
            return (255, 255, 255)
        if self._instance.rgb_color:
            return match_max_scale((255,), self._instance.rgb_color)
        return None

    @property
    def effect(self) -> str | None:
        """Return currently active effect or Off in white mode."""
        if self._instance.color_mode == ColorMode.WHITE:
            return "Off"
        return self._instance.effect

    @property
    def effect_list(self) -> list[str]:
        """Return list of supported lighting effects."""
        return self._instance.supported_effects

    @property
    def supported_features(self) -> LightEntityFeature:
        """Return supported entity features."""
        return LightEntityFeature.EFFECT

    @property
    def color_mode(self) -> ColorMode | None:
        """Return currently active ColorMode."""
        return self._instance.color_mode

    @property
    def device_info(self) -> DeviceInfo:
        """Return device registry information."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self._instance.mac)},
            name=self.name,
            manufacturer="Beurer",
            model="TL 100",
        )
        if self._instance.firmware_version:
            info["sw_version"] = self._instance.firmware_version
        return info

    def _transform_color_brightness(self, color: tuple[int, int, int], set_brightness: int) -> tuple[int, ...]:
        """Scale RGB colors according to desired brightness.

        Args:
            color: Original RGB color tuple.
            set_brightness: Target brightness value (0-255).

        Returns:
            Brightness-scaled RGB color tuple.
        """
        rgb = match_max_scale((255,), color)
        return tuple(c * set_brightness // 255 for c in rgb)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the light or adjust properties.

        Args:
            **kwargs: Light attributes such as brightness, rgb_color, effect.

        Raises:
            HomeAssistantError: If communication with the device fails.
        """
        LOGGER.debug("Turning light on with args: %s", kwargs)
        try:
            if not kwargs:
                await self._instance.turn_on()
                return

            color_mode = kwargs.get(ATTR_COLOR_MODE)

            # White mode or explicit ATTR_WHITE requested
            if color_mode in (ColorMode.WHITE, "white") or ATTR_WHITE in kwargs:
                white_val = kwargs.get(ATTR_WHITE)
                if isinstance(white_val, bool):
                    intensity = self._instance.white_brightness or 255 if white_val else 0
                elif isinstance(white_val, int):
                    intensity = white_val
                else:
                    intensity = kwargs.get(ATTR_BRIGHTNESS) or self._instance.white_brightness or 255
                await self._instance.set_white(intensity)
                return

            # RGB color requested or explicit RGB color mode
            if ATTR_RGB_COLOR in kwargs or color_mode in (ColorMode.RGB, "rgb"):
                if ATTR_RGB_COLOR in kwargs:
                    await self._instance.set_color(kwargs[ATTR_RGB_COLOR])
                elif not self._instance._color_on:
                    await self._instance.set_color(self._instance.rgb_color or (255, 255, 255))

                if ATTR_BRIGHTNESS in kwargs:
                    await self._instance.set_color_brightness(kwargs[ATTR_BRIGHTNESS])

            # Brightness adjustment without explicit color mode
            elif ATTR_BRIGHTNESS in kwargs:
                brightness = kwargs[ATTR_BRIGHTNESS]
                if self._instance.color_mode == ColorMode.RGB:
                    await self._instance.set_color_brightness(brightness)
                else:
                    await self._instance.set_white(brightness)

            # Effect requested
            if ATTR_EFFECT in kwargs:
                await self._instance.set_effect(kwargs[ATTR_EFFECT])
        except (BleakError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={
                    "name": self.name or self._instance.mac,
                    "error": str(err),
                },
            ) from err

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light.

        Args:
            **kwargs: Optional arguments from HA turn_off call.

        Raises:
            HomeAssistantError: If communication with the device fails.
        """
        try:
            await self._instance.turn_off()
        except (BleakError, TimeoutError, OSError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="communication_error",
                translation_placeholders={
                    "name": self.name or self._instance.mac,
                    "error": str(err),
                },
            ) from err

    async def async_update(self) -> None:
        """Poll or refresh state from device."""
        await self._instance.update()
