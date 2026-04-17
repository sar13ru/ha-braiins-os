from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BraiinsOSCoordinator


SENSORS = [
    ("hashrate_th", "Hashrate", "TH/s", 2),
    ("temp_avg", "Temperature", "°C", 1),
    ("power_w", "Power", "W", 0),
    ("fan_rpm", "Fan Speed", "rpm", 0),
    ("efficiency_j_th", "Efficiency", "J/TH", 2),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BraiinsOSCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities = [
        BraiinsSensor(coordinator, entry, key, name, unit, precision)
        for key, name, unit, precision in SENSORS
    ]

    async_add_entities(entities)


class BraiinsSensor(CoordinatorEntity[BraiinsOSCoordinator], SensorEntity):
    def __init__(
        self,
        coordinator: BraiinsOSCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        unit: str,
        precision: int,
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._precision = precision
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_native_unit_of_measurement = unit
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_config_entry_id = entry.entry_id
        host = str(entry.data.get(CONF_HOST, entry.title or "")).strip()
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=host or entry.title or "Braiins OS",
            manufacturer="Braiins",
            model="Braiins OS",
        )

    @property
    def native_value(self) -> float | None:
        data: dict[str, Any] | None = self.coordinator.data
        if not isinstance(data, dict):
            return None

        value = data.get(self._key)
        if value is None:
            return None
        if not isinstance(value, (int, float)):
            return None

        return round(float(value), self._precision)
