"""Config flow for Beurer BLE integration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, override

import probatio as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_MAC
from homeassistant.helpers.device_registry import format_mac

from .beurer import BeurerInstance, discover, get_device
from .const import DOMAIN, LOGGER

MANUAL_MAC: str = "manual"

# Contexts in which the shared validate step runs. The step needs to know
# whether a successful blink test has to create a new entry, refresh the data
# of the existing entry (reauth) or apply the new settings (reconfigure).
MODE_INITIAL: str = "initial"
MODE_REAUTH: str = "reauth"
MODE_RECONFIGURE: str = "reconfigure"


class BeurerFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Beurer BLE integration."""

    VERSION: int = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self.mac: str | None = None
        self.beurer_instance: BeurerInstance | None = None
        self.name: str | None = None
        self._mode: str = MODE_INITIAL

    def _current_title(self) -> str:
        """Return the title to give the config entry.

        Returns:
            The existing title during reauth, otherwise the configured name.
        """
        if self._mode == MODE_REAUTH:
            return self._get_reauth_entry().title
        return self.name or "Beurer TL 100"

    def _finish(self) -> ConfigFlowResult:
        """Finish the flow according to the current mode.

        Returns:
            ConfigFlowResult creating a new entry, or updating the existing one.
        """
        data = {CONF_MAC: self.mac, "name": self.name}
        if self._mode == MODE_REAUTH:
            return self.async_update_reload_and_abort(self._get_reauth_entry(), data=data)
        if self._mode == MODE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(),
                title=self.name or "Beurer TL 100",
                data=data,
            )
        return self.async_create_entry(title=self._current_title(), data=data)

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial user setup step.

        Args:
            user_input: User submitted form data.

        Returns:
            ConfigFlowResult showing form or transitioning to next step.
        """
        if user_input is not None:
            if user_input["mac"] == MANUAL_MAC:
                return await self.async_step_manual()

            self.mac = user_input["mac"]
            self.name = user_input["name"]
            await self.async_set_unique_id(format_mac(self.mac))
            self._abort_if_unique_id_configured()
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

    @override
    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak) -> ConfigFlowResult:
        """Handle bluetooth discovery step.

        Args:
            discovery_info: Discovery information from Bluetooth advertisement.

        Returns:
            ConfigFlowResult moving to bluetooth confirmation form or aborting.
        """
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self.mac = discovery_info.address
        self.name = discovery_info.name or "TL 100"
        self.context["title_placeholders"] = {"name": self.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm discovery of a Beurer device.

        Args:
            user_input: User submission on confirmation.

        Returns:
            ConfigFlowResult proceeding to validation form or showing confirmation form.
        """
        if user_input is not None:
            return await self.async_step_validate()

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self.name or "Beurer TL 100"},
        )

    async def async_step_validate(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Validate connection by blinking the light.

        This step is shared by the initial setup, the reauthentication and the
        reconfiguration flows; ``_mode`` decides what a successful blink test
        results in.

        Args:
            user_input: User validation feedback.

        Returns:
            ConfigFlowResult creating or updating the entry, aborting, or prompting retry.
        """
        if user_input is not None:
            if "flicker" in user_input:
                if user_input["flicker"]:
                    return self._finish()
                return self.async_abort(reason="cannot_validate")

            if "retry" in user_input and not user_input["retry"]:
                return self.async_abort(reason="cannot_connect")

        error = await self.toggle_light()

        if error:
            return self.async_show_form(
                step_id="validate", data_schema=vol.Schema({vol.Required("retry"): bool}), errors={"base": "connect"}
            )

        return self.async_show_form(step_id="validate", data_schema=vol.Schema({vol.Required("flicker"): bool}), errors={})

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manual MAC address entry step.

        Args:
            user_input: Submitted MAC and name.

        Returns:
            ConfigFlowResult showing form or proceeding to validation.
        """
        if user_input is not None:
            self.mac = user_input["mac"]
            self.name = user_input["name"]
            await self.async_set_unique_id(format_mac(self.mac))
            self._abort_if_unique_id_configured()
            return await self.async_step_validate()

        return self.async_show_form(
            step_id="manual", data_schema=vol.Schema({vol.Required("mac"): str, vol.Required("name"): str}), errors={}
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication for an existing entry.

        ``async_setup_entry`` calls ``entry.async_start_reauth`` when the lamp
        is no longer reachable at its stored address, which lands the user here.

        Args:
            entry_data: Current data of the config entry.

        Returns:
            ConfigFlowResult showing the reauth confirmation form.
        """
        self._mode = MODE_REAUTH
        self.mac = entry_data.get(CONF_MAC)
        self.name = entry_data.get("name")
        self.context["title_placeholders"] = {"name": self.name or "Beurer TL 100"}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user fix the address of the lamp before validating again.

        Args:
            user_input: Submitted MAC address and name.

        Returns:
            ConfigFlowResult showing the form, advancing to validation, or updating the entry.
        """
        if user_input is not None:
            self.mac = user_input["mac"]
            self.name = user_input["name"]
            return await self.async_step_validate()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("mac", default=self.mac or ""): str,
                    vol.Required("name", default=self.name or "Beurer TL 100"): str,
                }
            ),
            description_placeholders={"name": self.name or "Beurer TL 100"},
            errors={},
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Let the user change the address or name of an existing entry.

        Args:
            user_input: Submitted MAC address and name.

        Returns:
            ConfigFlowResult showing the form, advancing to validation, or updating the entry.
        """
        self._mode = MODE_RECONFIGURE
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            self.mac = user_input["mac"]
            self.name = user_input["name"]
            await self.async_set_unique_id(format_mac(self.mac))
            self._abort_if_unique_id_mismatch(reason="wrong_device")
            return await self.async_step_validate()

        self.mac = entry.data.get(CONF_MAC)
        self.name = entry.data.get("name")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required("mac", default=self.mac or ""): str,
                    vol.Required("name", default=self.name or "Beurer TL 100"): str,
                }
            ),
            description_placeholders={"name": self.name or "Beurer TL 100"},
            errors={},
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
                await self.beurer_instance.disconnect(closing=True)
        return None
