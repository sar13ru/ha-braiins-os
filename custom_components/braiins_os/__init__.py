from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .config_flow import CONF_BACKEND
from .coordinator import BraiinsOSCoordinator

PLATFORMS = ["sensor"]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    host = (
        entry.data.get(CONF_HOST)
        or entry.options.get(CONF_HOST)
        or entry.unique_id
        or entry.title
    )
    backend = (
        entry.data.get(CONF_BACKEND)
        or entry.options.get(CONF_BACKEND)
        or "grpc"
    )

    if not entry.data.get(CONF_HOST):
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_HOST: str(host).strip(),
                CONF_BACKEND: str(backend).strip().lower(),
            },
        )

    coordinator = BraiinsOSCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
