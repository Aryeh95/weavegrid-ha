"""Sensor entities for WeaveGrid."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import WeaveGridVehicleData
from .const import DOMAIN, format_status_key
from .coordinator import WeaveGridCoordinator
from .entity import WeaveGridEntity


def _parse_ts(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp from WeaveGrid into a timezone-aware datetime."""
    if not raw:
        return None
    parsed = dt_util.parse_datetime(raw)
    if parsed is not None and parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt_util.UTC)
    return parsed


def _latest_session_attrs(v: WeaveGridVehicleData) -> dict[str, Any]:
    if not v.recent_sessions:
        return {}
    return v.recent_sessions[0].as_dict()


@dataclass(frozen=True, kw_only=True)
class WeaveGridSensorDescription(SensorEntityDescription):
    """Describes a WeaveGrid sensor."""

    value_fn: Callable[[WeaveGridVehicleData], Any]
    attrs_fn: Callable[[WeaveGridVehicleData], dict[str, Any]] | None = None
    include_fn: Callable[[WeaveGridVehicleData], bool] = lambda _: True


SENSORS: tuple[WeaveGridSensorDescription, ...] = (
    WeaveGridSensorDescription(
        key="charging_status",
        name="Charging Status",
        icon="mdi:car-electric",
        value_fn=lambda v: format_status_key(v.status_key),
        attrs_fn=lambda v: {
            "raw_status_key": v.status_key,
            "plan_id": v.plan_id,
            "plan_outcome": v.plan_outcome,
            "off_peak_energy_percent": v.off_peak_energy_percent,
            "charge_by_times": (v.mc_settings or {}).get("chargeByTimes"),
            "solar_hours": (v.mc_settings or {}).get("solarHours"),
            "sms_preview": v.sms_preview,
            "time_zone": v.time_zone,
        },
    ),
    WeaveGridSensorDescription(
        key="charge_start",
        name="Scheduled Charge Start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
        value_fn=lambda v: _parse_ts(v.charge_start_dttm),
    ),
    WeaveGridSensorDescription(
        key="next_charge_start",
        name="Next Charge Start",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:calendar-clock",
        value_fn=lambda v: _parse_ts(v.next_charge_start_dttm),
    ),
    WeaveGridSensorDescription(
        key="ready_by",
        name="Target Ready By",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check-outline",
        value_fn=lambda v: _parse_ts(v.ready_by_dttm),
    ),
    WeaveGridSensorDescription(
        key="estimated_miles_added",
        name="Estimated Range Added",
        native_unit_of_measurement=UnitOfLength.MILES,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:map-marker-distance",
        value_fn=lambda v: round(v.miles_added_by_ready_time, 1)
        if v.miles_added_by_ready_time is not None
        else None,
    ),
    WeaveGridSensorDescription(
        key="battery_soc",
        name="Battery Level",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        include_fn=lambda v: (not v.is_evse) or (v.current_soc is not None),
        value_fn=lambda v: v.current_soc,
        attrs_fn=lambda v: {
            "target_soc": v.target_soc,
            "soc_at_ready_by_time": v.soc_at_ready_time,
            "last_read": v.battery_last_read_dttm,
        },
    ),
    WeaveGridSensorDescription(
        key="last_session_cost",
        name="Last Session Cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        suggested_display_precision=2,
        icon="mdi:currency-usd",
        value_fn=lambda v: round(v.recent_sessions[0].charge_cost, 2)
        if v.recent_sessions and v.recent_sessions[0].charge_cost is not None
        else None,
        attrs_fn=_latest_session_attrs,
    ),
    WeaveGridSensorDescription(
        key="last_session_energy",
        name="Last Session Energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        icon="mdi:lightning-bolt",
        value_fn=lambda v: round(v.recent_sessions[0].energy_kwh, 2)
        if v.recent_sessions and v.recent_sessions[0].energy_kwh is not None
        else None,
        attrs_fn=_latest_session_attrs,
    ),
    WeaveGridSensorDescription(
        key="last_session_duration",
        name="Last Session Duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        icon="mdi:timer-outline",
        value_fn=lambda v: round(v.recent_sessions[0].charge_hours, 2)
        if v.recent_sessions and v.recent_sessions[0].charge_hours is not None
        else None,
        attrs_fn=_latest_session_attrs,
    ),
    WeaveGridSensorDescription(
        key="recent_charging_sessions",
        name="Recent Charging Sessions",
        icon="mdi:history",
        value_fn=lambda v: v.recent_sessions[0].usage_date
        if v.recent_sessions and v.recent_sessions[0].usage_date
        else "No recent sessions",
        attrs_fn=lambda v: {
            "session_count": len(v.recent_sessions),
            "total_recent_energy_kwh": round(
                sum(s.energy_kwh or 0.0 for s in v.recent_sessions), 2
            ),
            "total_recent_cost": round(
                sum(s.charge_cost or 0.0 for s in v.recent_sessions), 2
            ),
            "currency": v.cost_unit,
            "sessions": [s.as_dict() for s in v.recent_sessions],
        },
    ),
    WeaveGridSensorDescription(
        key="cost_7d",
        name="7-Day Charging Cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        suggested_display_precision=2,
        icon="mdi:cash-clock",
        value_fn=lambda v: round(v.cost_7d, 2),
    ),
    WeaveGridSensorDescription(
        key="energy_7d",
        name="7-Day Charging Energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        icon="mdi:meter-electric-outline",
        value_fn=lambda v: round(v.energy_7d_kwh, 2),
    ),
    WeaveGridSensorDescription(
        key="cost_30d",
        name="30-Day Charging Cost",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        suggested_display_precision=2,
        icon="mdi:cash-multiple",
        value_fn=lambda v: round(v.cost_30d, 2),
        attrs_fn=lambda v: {
            "off_peak_cost_30d": round(v.off_peak_cost_30d, 2),
            "smart_charging_cost_30d": round(v.smart_cost_30d, 2),
            "currency": v.cost_unit,
        },
    ),
    WeaveGridSensorDescription(
        key="energy_30d",
        name="30-Day Charging Energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        icon="mdi:meter-electric",
        value_fn=lambda v: round(v.energy_30d_kwh, 2),
        attrs_fn=lambda v: {
            "off_peak_energy_30d_kwh": round(v.off_peak_energy_30d_kwh, 2),
        },
    ),
    WeaveGridSensorDescription(
        key="smart_score_30d",
        name="30-Day Smart Score",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        icon="mdi:leaf-circle-outline",
        value_fn=lambda v: round(v.smart_score_30d, 1)
        if v.smart_score_30d is not None
        else None,
        attrs_fn=lambda v: {
            "smart_score_type": v.smart_score_type,
        },
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up WeaveGrid sensors."""
    coordinator: WeaveGridCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[WeaveGridSensor] = []
    for vid, veh in coordinator.data.vehicles.items():
        for desc in SENSORS:
            if desc.include_fn(veh):
                entities.append(WeaveGridSensor(coordinator, vid, desc))
    async_add_entities(entities)


class WeaveGridSensor(WeaveGridEntity, SensorEntity):
    """Representation of a WeaveGrid sensor."""

    entity_description: WeaveGridSensorDescription

    def __init__(
        self,
        coordinator: WeaveGridCoordinator,
        vehicle_id: str,
        description: WeaveGridSensorDescription,
    ) -> None:
        super().__init__(coordinator, vehicle_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        veh = self.vehicle
        if veh is None:
            return None
        return self.entity_description.value_fn(veh)

    @property
    def native_unit_of_measurement(self) -> str | None:
        veh = self.vehicle
        if (
            self.entity_description.device_class == SensorDeviceClass.MONETARY
            and veh is not None
            and veh.cost_unit
        ):
            return veh.cost_unit
        return self.entity_description.native_unit_of_measurement

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        veh = self.vehicle
        if veh is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(veh)
