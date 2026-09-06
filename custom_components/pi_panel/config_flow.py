"""Setup dialog: where the config server is, and its password."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT
from homeassistant.exceptions import ConfigEntryAuthFailed

from .const import DEFAULT_PORT, DOMAIN
from .coordinator import PanelServer, PanelServerError


class PiPanelConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            server = PanelServer(
                self.hass,
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input[CONF_PASSWORD],
            )
            try:
                # Fetching the fleet, not merely logging in: it proves the
                # credentials and that this really is a panel server, so a
                # wrong port answered by something else fails here rather than
                # at the first refresh with a confusing traceback.
                await server.panels()
            except ConfigEntryAuthFailed:
                errors["base"] = "invalid_auth"
            except PanelServerError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title="Panel fleet", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    # The host and port panels use, not the ingress address.
                    # Ingress needs Home Assistant's own auth and is reachable
                    # only from inside HA, so it is the wrong one here even
                    # though it is the one the operator sees in the sidebar.
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
