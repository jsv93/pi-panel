"""The panel's diagnostics overlay, as something an automation can turn on."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PiPanelEntry
from .coordinator import PanelServerError
from .entity import PanelEntity

DIAGNOSTICS = SwitchEntityDescription(
    key="diagnostics",
    translation_key="diagnostics",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PiPanelEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add(PanelDiagnostics(coordinator, pid, DIAGNOSTICS) for pid in coordinator.data)


class PanelDiagnostics(PanelEntity, SwitchEntity):
    def __init__(self, coordinator, panel_id, description) -> None:
        super().__init__(coordinator, panel_id, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return bool((self.panel.get("display") or {}).get("diagnostics"))

    async def _set(self, on: bool) -> None:
        try:
            await self.coordinator.server.set_display(self._panel_id, {"diagnostics": on})
        except PanelServerError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)
