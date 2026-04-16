from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

CONF_BACKEND = "backend"
BACKENDS = ("grpc", "s9")


class BraiinsOSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = str(user_input[CONF_HOST]).strip()
            backend = str(user_input[CONF_BACKEND]).strip().lower()

            if backend not in BACKENDS:
                errors[CONF_BACKEND] = "invalid_backend"
            elif not host:
                errors[CONF_HOST] = "required"
            else:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=host,
                    data={
                        CONF_HOST: host,
                        CONF_BACKEND: backend,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_BACKEND, default="grpc"): vol.In(BACKENDS),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
