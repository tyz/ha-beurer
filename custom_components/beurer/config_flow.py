"""Config flow for Beurer BLE integration."""

from __future__ import annotations

import asyncio
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
# whether a successful blink test has to create a new entry or apply the new
# settings to the existing entry (reconfigure).
MODE_INITIAL: str = "initial"
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
            The configured name, or the default title.
        """
        return self.name or "Beurer TL 100"

    def _finish(self) -> ConfigFlowResult:
        """Finish the flow according to the current mode.

        Returns:
            ConfigFlowResult creating a new entry, or updating the existing one.
        """
        data = {CONF_MAC: self.mac, "name": self.name}
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
        candidates = await self._async_discover_candidates()
        candidates = {address: name for address, name in candidates.items() if format_mac(address) not in already_configured}

        if not candidates:
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("mac"): vol.In({**candidates, MANUAL_MAC: "Manually add a MAC address"}),
                    vol.Required("name"): str,
                }
            ),
            errors={},
        )

    async def _async_discover_candidates(self) -> dict[str, str]:
        """Return advertised TL 100 lamps as an address to name mapping.

        Home Assistant's Bluetooth stack is used when available: it already
        holds every advertisement seen by the local adapter and by any
        Bluetooth proxy, so no fresh scan is needed. Only when the component is
        missing entirely does this fall back to a direct scan, which cannot see
        devices that are reachable through a proxy.

        Returns:
            Mapping of address to advertised name.
        """
        if hasattr(self, "hass") and self.hass:
            try:
                from homeassistant.components import bluetooth

                infos = bluetooth.async_discovered_service_info(self.hass, connectable=True)
            except (ImportError, AttributeError) as err:
                LOGGER.debug("Bluetooth component unavailable, falling back to a direct scan: %s", err)
            else:
                return {
                    info.address: info.name or "Beurer TL 100"
                    for info in infos
                    if info.name and info.name.lower().startswith("tl100")
                }

        devices = await discover()
        return {device.address: device.name or "Beurer TL 100" for device in devices}

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

        This step is shared by the initial setup and the reconfiguration flow;
        ``_mode`` decides what a successful blink test results in.

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

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Rename an existing entry after re-validating that the lamp answers.

        The address is deliberately not editable. Entity unique IDs are derived
        from it (``57:4C:42:80:71:BA``, ``57:4C:42:80:71:BA_timer``, ...), so a
        different address would create a new set of entities and orphan the
        existing ones, taking their entity IDs, dashboards and automations with
        them. Pointing the entry at another lamp therefore means deleting and
        re-adding it, which the documentation states explicitly.

        Args:
            user_input: Submitted name.

        Returns:
            ConfigFlowResult showing the form, advancing to validation, or updating the entry.
        """
        self._mode = MODE_RECONFIGURE
        entry = self._get_reconfigure_entry()
        self.mac = entry.data.get(CONF_MAC)
        if user_input is not None:
            self.name = user_input["name"]
            return await self.async_step_validate()

        self.name = entry.data.get("name")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required("name", default=self.name or "Beurer TL 100"): str,
                }
            ),
            description_placeholders={"name": self.name or "Beurer TL 100", "mac": self.mac or ""},
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
        used_ha_bluetooth = False
        if hasattr(self, "hass") and self.hass:
            try:
                from homeassistant.components import bluetooth

                device = bluetooth.async_ble_device_from_address(self.hass, self.mac, connectable=True)
                used_ha_bluetooth = True
            except (ImportError, AttributeError) as err:
                LOGGER.debug("Bluetooth component unavailable: %s", err)

        if device is None and not used_ha_bluetooth:
            # A direct scan only reaches adapters attached to this host. When
            # Home Assistant's stack is present it is authoritative: a lamp it
            # cannot resolve is not reachable, including through a proxy, so
            # scanning again would just add a slow round trip.
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
                # Closing marks the instance as permanently shutting down so a
                # stray disconnect cannot schedule a reconnect after the flow
                # ends. A closed instance also refuses to connect again, so a
                # retry of this step must start from a fresh one.
                await self.beurer_instance.disconnect(closing=True)
                self.beurer_instance = None
        return None
