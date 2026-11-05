"""Binary sensor entities for WeaveGrid."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import WeaveGridVehicleData
from .const import DOMAIN
from .coordinator import WeaveGridCoordinator
from .entity import WeaveGridEntity


@dataclass(frozen=True, kw_only=True)
class WeaveGridBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a WeaveGrid binary sensor."""

    is_on_fn: Callable[[WeaveGridVehicleData], bool | None]
    attrs_fn: Callable[[WeaveGridVehicleData], dict[str, Any]] | None = None


BINARY_SENSORS: tuple[WeaveGridBinarySensorDescription, ...] = (
    WeaveGridBinarySensorDescription(
        key="plugged_in",
        name="Plugged In",
        device_class=BinarySensorDeviceClass.PLUG,
        is_on_fn=lambda v: v.is_plugged_in,
    ),
    WeaveGridBinarySensorDescription(
        key="charging",
        name="Charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
        is_on_fn=lambda v: v.is_charging,
    ),
    WeaveGridBinarySensorDescription(
        key="at_home",
        name="At Home",
        device_class=BinarySensorDeviceClass.PRESENCE,
        is_on_fn=lambda v: v.is_home,
    ),
    WeaveGridBinarySensorDescription(
        key="smart_charging_active",
        name="Smart Charging",
        icon="mdi:ev-station",
        is_on_fn=lambda v: bool(v.is_active and v.has_mc_feature),
        attrs_fn=lambda v: {
            "dr_feature_status": v.dr_feature_status,
            "rate_schedule_code": v.rate_schedule_code,
            "rate_type": v.current_rate_type,
            "off_peak_windows": v.off_peak_windows,
            "deactivated_reason": v.deactivated_reason,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WeaveGrid binary sensors."""
    coordinator: WeaveGridCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[WeaveGridBinarySensor] = []
    for vid in coordinator.data.vehicles:
        for desc in BINARY_SENSORS:
            entities.append(WeaveGridBinarySensor(coordinator, vid, desc))
    async_add_entities(entities)


class WeaveGridBinarySensor(WeaveGridEntity, BinarySensorEntity):
    """Representation of a WeaveGrid binary sensor."""

    entity_description: WeaveGridBinarySensorDescription

    def __init__(
        self,
        coordinator: WeaveGridCoordinator,
        vehicle_id: str,
        description: WeaveGridBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        veh = self.vehicle
        if veh is None:
            return None
        return self.entity_description.is_on_fn(veh)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        veh = self.vehicle
        if veh is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(veh)
