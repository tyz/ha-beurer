"""Platform for light integration with Beurer TL 100."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_WHITE,
    PLATFORM_SCHEMA,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import match_max_scale

from .beurer import BeurerInstance
from .const import DOMAIN, LOGGER

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({vol.Required(CONF_MAC): cv.string})
SCAN_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_devices: AddEntitiesCallback,
) -> None:
    """Set up the Beurer light platform from a config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Config entry containing device details.
        async_add_devices: Callback to register entities with HA.
    """
    LOGGER.debug("Setting up device from light")
    instance: BeurerInstance = hass.data[DOMAIN][config_entry.entry_id]
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

    async def async_added_to_hass(self) -> None:
        """Register callbacks after being added to Home Assistant."""
        self._instance.set_update_callback(self.update_callback)
        await self._instance.update()

    def update_callback(self) -> None:
        """Write updated state to Home Assistant state machine."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if device state is known."""
        return self._instance.is_on is not None

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
        """Return the current RGB color tuple scaled to maximum intensity."""
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
        return DeviceInfo(
            identifiers={(DOMAIN, self._instance.mac)},
            name=self.name,
            manufacturer="Beurer",
            model="TL 100",
        )

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
        """
        LOGGER.debug("Turning light on with args: %s", kwargs)
        if not kwargs:
            await self._instance.turn_on()
            return

        if kwargs.get(ATTR_WHITE) is not None:
            await self._instance.set_white(kwargs[ATTR_WHITE])

        elif kwargs.get(ATTR_RGB_COLOR):
            color = kwargs[ATTR_RGB_COLOR]
            await self._instance.set_color(color)
            if kwargs.get(ATTR_BRIGHTNESS):
                await self._instance.set_color_brightness(kwargs[ATTR_BRIGHTNESS])

        elif kwargs.get(ATTR_BRIGHTNESS):
            brightness = kwargs[ATTR_BRIGHTNESS]
            if self._instance.color_mode == ColorMode.RGB:
                await self._instance.set_color_brightness(brightness)
            else:
                await self._instance.set_white(brightness)

        if kwargs.get(ATTR_EFFECT):
            await self._instance.set_effect(kwargs[ATTR_EFFECT])

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the light.

        Args:
            **kwargs: Optional arguments from HA turn_off call.
        """
        await self._instance.turn_off()

    async def async_update(self) -> None:
        """Poll or refresh state from device."""
        await self._instance.update()
