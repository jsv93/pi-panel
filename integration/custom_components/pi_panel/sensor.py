"""Per-panel readings, plus the two that answer "is this panel current"."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PiPanelEntry
from .entity import PanelEntity


@dataclass(frozen=True, kw_only=True)
class PanelSensor(SensorEntityDescription):
    value: Callable[[dict, dict], object]


SENSORS: tuple[PanelSensor, ...] = (
    PanelSensor(
        key="cpu_temp",
        translation_key="cpu_temp",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda p, m: m.get("cpu_temp"),
    ),
    PanelSensor(
        key="disk_free",
        translation_key="disk_free",
        native_unit_of_measurement="%",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Reported as "71%" by the agent; the trailing sign has to come off or
        # Home Assistant records a string and the history graph stays empty.
        value=lambda p, m: _pct(m.get("disk_free")),
    ),
    PanelSensor(
        key="config_version",
        translation_key="config_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda p, m: p.get("config_version"),
    ),
    PanelSensor(
        key="config_pending",
        translation_key="config_pending",
        entity_category=EntityCategory.DIAGNOSTIC,
        # The gap between what the server holds and what the panel reports
        # running. Non-zero means a push has not landed yet -- the one number
        # that says a panel is out of date, which is otherwise two numbers to
        # compare by eye.
        value=lambda p, m: max(0, (p.get("latest_version") or 0)
                               - (p.get("config_version") or 0)),
    ),
    PanelSensor(
        key="agent_version",
        translation_key="agent_version",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda p, m: m.get("ui_version"),
    ),
    PanelSensor(
        key="backlight",
        translation_key="backlight",
        entity_category=EntityCategory.DIAGNOSTIC,
        value=lambda p, m: m.get("backlight"),
    ),
)


def _pct(v):
    try:
        return float(str(v).rstrip("%"))
    except (TypeError, ValueError):
        return None


async def async_setup_entry(
    hass: HomeAssistant, entry: PiPanelEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add(
        PanelSensorEntity(coordinator, pid, desc)
        for pid in coordinator.data
        for desc in SENSORS
    )


class PanelSensorEntity(PanelEntity, SensorEntity):
    entity_description: PanelSensor

    def __init__(self, coordinator, panel_id, description: PanelSensor) -> None:
        super().__init__(coordinator, panel_id, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        return self.entity_description.value(self.panel, self.metrics)
