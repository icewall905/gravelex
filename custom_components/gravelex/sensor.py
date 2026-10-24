"""Dynamic metric sensors for GravelEx."""

from __future__ import annotations

import math
import re
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import GravelExCoordinator

_UNIT_MAP = {
    "kg": UnitOfMass.KILOGRAMS, "g": UnitOfMass.GRAMS, "bpm": "bpm", "h": UnitOfTime.HOURS,
    "min": UnitOfTime.MINUTES, "s": UnitOfTime.SECONDS, "%": "%", "kcal": "kcal", "m": "m",
    "score": "score",
}
_KEY_RE = re.compile(r"[^a-z0-9_]+")


def _safe_key(value: str) -> str:
    return _KEY_RE.sub("_", value.lower()).strip("_") or "metric"


DEFAULT_UNITS={
    **{k:'kg' for k in ('weight','muscle_mass_kg','bone_mass_kg','fat_mass_kg','fat_free_mass_kg','weight_change_7d','weight_change_28d')},
    **{k:'%' for k in ('spo2','watch_battery','body_fat_pct','body_water_pct')},
    **{k:'score' for k in ('readiness','sleep_score','overnight_strain')},
    **{k:'bpm' for k in ('heart_rate','overnight_pulse')},
    **{k:'h' for k in ('sleep_hours','sleep_restful_hours','sleep_target_hours')},
    **{k:'s' for k in ('upload_age_seconds','snapshot_active_seconds','snapshot_sleep_seconds','snapshot_restful_sleep_seconds','last_workout_duration')},
    **{k:'kcal' for k in ('bmr_estimate','active_energy_today','resting_energy_today','snapshot_active_energy','snapshot_resting_energy')},
    **{k:'min' for k in ('active_minutes_today','intensity_minutes_week','intensity_minutes_7d','sleep_regularity_sd')},
    **{k:'m' for k in ('distance_today','snapshot_distance')},
    'steps':'steps','steps_today':'steps','hrv_rmssd':'ms','breathing_rate':'breaths/min',
    'vo2max_estimate':'mL/kg/min','training_load':'load','acute_load':'load','chronic_load':'load','training_balance':'load',
    'training_baseline_days':'d','training_known_days_7':'d',
}


def _description(key: str, metric: dict[str, Any]) -> SensorEntityDescription:
    unit = metric.get("unit",DEFAULT_UNITS.get(key))
    return SensorEntityDescription(
        key=key,
        state_class=SensorStateClass.MEASUREMENT if key!='last_workout_type' else None,
        name=str(metric.get("name") or key.replace("_", " ").title()),
        native_unit_of_measurement=_UNIT_MAP.get(unit, unit if isinstance(unit, str) and len(unit) <= 32 else None),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GravelExCoordinator = hass.data[DOMAIN][entry.entry_id]
    seen=set()
    @callback
    def discover():
        keys=set((coordinator.data or {}).get('metrics',{}))-seen
        seen.update(keys)
        async_add_entities([GravelExSensor(coordinator,entry,key) for key in sorted(keys)])
    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class GravelExSensor(CoordinatorEntity[GravelExCoordinator], SensorEntity):
    """One metric returned by the server, including null metrics."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: GravelExCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._entry = entry
        metric = ((coordinator.data or {}).get("metrics") or {}).get(key) or {}
        self.entity_description = _description(key, metric)
        account_id = str(entry.data["account_id"])
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}|{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, str(entry.unique_id or entry.entry_id))},
            name=str((coordinator.data or {}).get("account", {}).get("display_name") or "GravelEx Health"),
            manufacturer="GravelEx",
            model="Health account",
        )

    @callback
    def _handle_coordinator_update(self):
        metric=((self.coordinator.data or {}).get('metrics') or {}).get(self._key)
        if isinstance(metric,dict): self.entity_description=_description(self._key,metric)
        super()._handle_coordinator_update()

    @property
    def native_value(self):
        metric = ((self.coordinator.data or {}).get("metrics") or {}).get(self._key) or {}
        value = metric.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value,str) and (len(value)>255 or self._key!='last_workout_type'):
            return None
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        metric = ((self.coordinator.data or {}).get("metrics") or {}).get(self._key) or {}
        return {
            "status": metric.get("status"),
            "estimated": metric.get("estimated"),
            "observed_at": metric.get("observed_at"),
            "source": metric.get("source"),
            "observed_minutes":metric.get('observed_minutes'),
            "elapsed_minutes":metric.get('elapsed_minutes'),
        }

