"""Panel display settings that take a value.

These write, which the config-authoring endpoints deliberately do not allow
from here. The distinction is that authoring a panel's configuration -- which
lights it shows, which speaker it drives -- has to happen in one place, whereas
turning the brightness down adjusts a value that already lives on the server,
through the server, with the server still holding the only copy. Nothing can
diverge, so nothing needs arbitrating.

The point of having them at all is automation, which is the one thing the
server's GUI cannot do and never will: dim at sunset, come up in the morning,
drop the glass tier on a panel that is struggling.
"""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PiPanelEntry
from .coordinator import PanelServerError
from .entity import PanelEntity


@dataclass(frozen=True, kw_only=True)
class PanelNumber(NumberEntityDescription):
    setting: str
    default: float


NUMBERS: tuple[PanelNumber, ...] = (
    PanelNumber(
        key="brightness",
        translation_key="brightness",
        setting="backlight_default",
        default=100,
        native_min_value=1,
        native_max_value=100,
        native_step=1,
        native_unit_of_measurement="%",
        mode=NumberMode.SLIDER,
    ),
    PanelNumber(
        key="wake_time",
        translation_key="wake_time",
        setting="idle_timeout_s",
        default=45,
        native_min_value=5,
        native_max_value=600,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=NumberDeviceClass.DURATION,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
    ),
    PanelNumber(
        key="blank_after",
        translation_key="blank_after",
        setting="backlight_off_s",
        default=0,
        native_min_value=0,
        native_max_value=3600,
        native_step=30,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=NumberDeviceClass.DURATION,
        entity_category=EntityCategory.CONFIG,
        mode=NumberMode.BOX,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PiPanelEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add(
        PanelNumberEntity(coordinator, pid, desc)
        for pid in coordinator.data
        for desc in NUMBERS
    )


class PanelNumberEntity(PanelEntity, NumberEntity):
    entity_description: PanelNumber

    def __init__(self, coordinator, panel_id, description: PanelNumber) -> None:
        super().__init__(coordinator, panel_id, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        display = self.panel.get("display") or {}
        return display.get(self.entity_description.setting, self.entity_description.default)

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.server.set_display(
                self._panel_id, {self.entity_description.setting: int(value)}
            )
        except PanelServerError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
