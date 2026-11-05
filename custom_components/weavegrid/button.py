"""Button entities for WeaveGrid ('Charge Now' override)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    """Set up WeaveGrid button entities."""
    coordinator: WeaveGridCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        WeaveGridChargeNowButton(coordinator, vid)
        for vid, veh in coordinator.data.vehicles.items()
        if veh.has_mc_feature and veh.is_active
    ]
    async_add_entities(entities)


class WeaveGridChargeNowButton(WeaveGridEntity, ButtonEntity):
    """Button that triggers WeaveGrid's 'Charge now' immediate charging override."""

    _attr_name = "Charge Now"
    _attr_icon = "mdi:lightning-bolt-circle"

    def __init__(
        self,
        coordinator: WeaveGridCoordinator,
        vehicle_id: str,
    ) -> None:
        super().__init__(coordinator, vehicle_id, "charge_now")

    async def async_press(self) -> None:
        """Trigger immediate charging override for this vehicle/EVSE."""
        await self.coordinator.async_trigger_charge_now(self._vehicle_id)
