from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BraiinsOSCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BraiinsOSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BraiinsHashrateSensor(coordinator, entry)])


class BraiinsHashrateSensor(CoordinatorEntity[BraiinsOSCoordinator], SensorEntity):
    def __init__(self, coordinator: BraiinsOSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "Hashrate"
        self._attr_unique_id = f"{entry.entry_id}_hashrate_th"
        self._attr_native_unit_of_measurement = "TH/s"

    @property
    def native_value(self) -> float | None:
        data: dict[str, Any] | None = self.coordinator.data
        if not isinstance(data, dict):
            return None
        value = data.get("hashrate_th")
        return value if isinstance(value, (int, float)) else None
