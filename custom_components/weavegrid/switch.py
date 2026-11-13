"""Switch entities for WeaveGrid managed charging preferences."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import WeaveGridCoordinator
from .entity import WeaveGridEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WeaveGrid switches."""
    coordinator: WeaveGridCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        WeaveGridPeakAvoidanceSwitch(coordinator, vid)
        for vid, veh in coordinator.data.vehicles.items()
        if veh.has_mc_feature and not veh.hide_mc_settings and veh.is_active
    ]
    async_add_entities(entities)


class WeaveGridPeakAvoidanceSwitch(WeaveGridEntity, SwitchEntity):
    """Switch controlling WeaveGrid's Peak Avoidance preference."""

    _attr_name = "Peak Avoidance"
    _attr_icon = "mdi:transmission-tower-export"

    def __init__(
        self,
        coordinator: WeaveGridCoordinator,
        vehicle_id: str,
    ) -> None:
        super().__init__(coordinator, vehicle_id, "peak_avoidance")

    @property
    def available(self) -> bool:
        """Only available when the current managed charging settings were read.

        Writing without them would overwrite the user's charging schedule.
        """
        veh = self.vehicle
        return super().available and veh is not None and bool(veh.mc_settings)

    @property
    def is_on(self) -> bool | None:
        veh = self.vehicle
        if veh is None or not veh.mc_settings:
            return None
        val = veh.mc_settings.get("enablePeakAvoidance")
        return bool(val) if val is not None else False

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        veh = self.vehicle
        if veh is None:
            return None
        mc = veh.mc_settings or {}
        return {
            "charge_by_times": mc.get("chargeByTimes"),
            "low_soc_protection": mc.get("enableLowSocProtection"),
            "solar_hours": mc.get("solarHours"),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable Peak Avoidance."""
        await self.coordinator.async_set_peak_avoidance(self._vehicle_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable Peak Avoidance."""
        await self.coordinator.async_set_peak_avoidance(self._vehicle_id, False)
