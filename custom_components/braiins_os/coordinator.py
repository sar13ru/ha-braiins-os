from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from .braiins_client.client import BraiinsClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .config_flow import CONF_BACKEND
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class BraiinsOSCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry
        self._host = str(entry.data[CONF_HOST])
        self._backend = str(entry.data[CONF_BACKEND])
        self._client = BraiinsClient(host=self._host, backend=self._backend)

        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{self._host}",
            update_interval=timedelta(seconds=30),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self._client.async_get_summary()
        except Exception as err:  # noqa: BLE001
            raise UpdateFailed(f"Error al obtener datos de {self._host}: {err}") from err

        if not isinstance(data, dict):
            raise UpdateFailed(f"Respuesta invalida desde {self._host}")

        if not data.get("ok") and data.get("error"):
            raise UpdateFailed(str(data["error"]))

        return data
