"""Base entity for WeaveGrid devices."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import WeaveGridVehicleData
from .const import DOMAIN
from .coordinator import WeaveGridCoordinator


class WeaveGridEntity(CoordinatorEntity[WeaveGridCoordinator]):
    """Base entity representing a WeaveGrid-managed EV or EVSE."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: WeaveGridCoordinator,
        vehicle_id: str,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._vehicle_id = vehicle_id
        self._attr_unique_id = f"weavegrid_{vehicle_id}_{key}"

    @property
    def vehicle(self) -> WeaveGridVehicleData | None:
        """Return current vehicle snapshot from coordinator."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.vehicles.get(self._vehicle_id)

    @property
    def available(self) -> bool:
        """Return True if coordinator succeeded and vehicle exists."""
        return super().available and self.vehicle is not None

    @property
    def device_info(self) -> DeviceInfo:
        """Group entities under a Home Assistant Device per vehicle/EVSE."""
        veh = self.vehicle
        util = self.coordinator.client.utility_acronym
        model_kind = "EV Charger (EVSE)" if (veh and veh.is_evse) else "Electric Vehicle"
        return DeviceInfo(
            identifiers={(DOMAIN, self._vehicle_id)},
            name=veh.display_name if veh else f"WeaveGrid {self._vehicle_id}",
            manufacturer=veh.oem_name if veh else "WeaveGrid",
            model=f"{model_kind} via WeaveGrid ({util.upper()})",
            configuration_url=f"{self.coordinator.client.base_url}/{util}/dashboard/",
        )
