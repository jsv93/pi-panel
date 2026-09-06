"""Is the panel there, and is it talking to Home Assistant."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PiPanelEntry
from .entity import PanelEntity


@dataclass(frozen=True, kw_only=True)
class PanelBinary(BinarySensorEntityDescription):
    value: Callable[[dict, dict], bool]


BINARY_SENSORS: tuple[PanelBinary, ...] = (
    PanelBinary(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        value=lambda p, m: bool(p.get("online")),
    ),
    PanelBinary(
        key="ha_connected",
        translation_key="ha_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        # The panel's own websocket to Home Assistant, which is separate from
        # whether the server can see the panel. A panel can be perfectly online
        # here and still show nothing on the wall because its token expired,
        # and that difference is the first thing worth knowing.
        value=lambda p, m: bool(m.get("ha_connected")),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PiPanelEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add(
        PanelBinarySensor(coordinator, pid, desc)
        for pid in coordinator.data
        for desc in BINARY_SENSORS
    )


class PanelBinarySensor(PanelEntity, BinarySensorEntity):
    entity_description: PanelBinary

    def __init__(self, coordinator, panel_id, description: PanelBinary) -> None:
        super().__init__(coordinator, panel_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return self.entity_description.value(self.panel, self.metrics)
