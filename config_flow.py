"""Config flow for Beurer BLE integration."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_MAC
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.device_registry import format_mac

from .beurer import BeurerInstance, discover, get_device
from .const import DOMAIN, LOGGER

MANUAL_MAC: str = "manual"


class BeurerFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Handle a config flow for Beurer BLE integration."""

    VERSION: int = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.mac: str | None = None
        self.beurer_instance: BeurerInstance | None = None
        self.name: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Handle the initial user setup step.

        Args:
            user_input: User submitted form data.

        Returns:
            FlowResult showing form or transitioning to next step.
        """
        if user_input is not None:
            if user_input["mac"] == MANUAL_MAC:
                return await self.async_step_manual()

            self.mac = user_input["mac"]
            self.name = user_input["name"]
            await self.async_set_unique_id(format_mac(self.mac))
            return await self.async_step_validate()

        already_configured = self._async_current_ids(False)
        devices = await discover()
        devices = [device for device in devices if format_mac(device.address) not in already_configured]

        if not devices:
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("mac"): vol.In(
                        {
                            **{device.address: device.name for device in devices},
                            MANUAL_MAC: "Manually add a MAC address",
                        }
                    ),
                    vol.Required("name"): str,
                }
            ),
            errors={},
        )

    async def async_step_validate(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Validate connection by blinking the light.

        Args:
            user_input: User validation feedback.

        Returns:
            FlowResult creating entry, aborting, or prompting retry.
        """
        if user_input is not None:
            if "flicker" in user_input:
                if user_input["flicker"]:
                    return self.async_create_entry(title=self.name or "Beurer", data={CONF_MAC: self.mac, "name": self.name})
                return self.async_abort(reason="cannot_validate")

            if "retry" in user_input and not user_input["retry"]:
                return self.async_abort(reason="cannot_connect")

        error = await self.toggle_light()

        if error:
            return self.async_show_form(
                step_id="validate", data_schema=vol.Schema({vol.Required("retry"): bool}), errors={"base": "connect"}
            )

        return self.async_show_form(step_id="validate", data_schema=vol.Schema({vol.Required("flicker"): bool}), errors={})

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Manual MAC address entry step.

        Args:
            user_input: Submitted MAC and name.

        Returns:
            FlowResult showing form or proceeding to validation.
        """
        if user_input is not None:
            self.mac = user_input["mac"]
            self.name = user_input["name"]
            await self.async_set_unique_id(format_mac(self.mac))
            return await self.async_step_validate()

        return self.async_show_form(
            step_id="manual", data_schema=vol.Schema({vol.Required("mac"): str, vol.Required("name"): str}), errors={}
        )

    async def toggle_light(self) -> Exception | None:
        """Toggle light during setup to confirm communication.

        Returns:
            None if successful, or Exception on error.
        """
        if not self.mac:
            return Exception("No MAC address specified")

        device = None
        if hasattr(self, "hass") and self.hass:
            try:
                from homeassistant.components import bluetooth

                device = bluetooth.async_ble_device_from_address(self.hass, self.mac, connectable=True)
            except (ImportError, AttributeError) as err:
                LOGGER.debug("Bluetooth component unavailable: %s", err)

        if device is None:
            device = await get_device(self.mac)
        if device is None:
            LOGGER.error("Was not able to find device with mac %s", self.mac)
            return Exception(f"Was not able to find device with mac {self.mac}")

        if not self.beurer_instance:
            self.beurer_instance = BeurerInstance(device)
        else:
            self.beurer_instance.set_device(device)

        try:
            LOGGER.debug("Going to update from config flow")
            await self.beurer_instance.update()
            LOGGER.debug("Finished updating from config flow, light is %s", self.beurer_instance.is_on)
            if self.beurer_instance.is_on:
                await self.beurer_instance.turn_off()
                await asyncio.sleep(2)
                await self.beurer_instance.turn_on()
            else:
                await self.beurer_instance.turn_on()
                await asyncio.sleep(2)
                await self.beurer_instance.turn_off()
        except Exception as error:  # noqa: BLE001
            LOGGER.error("Error while toggling light: %s", error)
            return error
        finally:
            if self.beurer_instance:
                await self.beurer_instance.disconnect()
        return None
