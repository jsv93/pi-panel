"""Reload, sync and restart.

Commands, not configuration, so these work under either config_owner. Telling a
panel to reload its page does not change what the page will show; only a config
write does that, and the server refuses those from whichever side does not own
them.
"""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PiPanelEntry
from .coordinator import PanelServerError
from .entity import PanelEntity

BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="reload", translation_key="reload", entity_category=EntityCategory.CONFIG
    ),
    ButtonEntityDescription(
        key="sync", translation_key="sync", entity_category=EntityCategory.CONFIG
    ),
    ButtonEntityDescription(
        key="restart", translation_key="restart", entity_category=EntityCategory.CONFIG
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PiPanelEntry, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    add(
        PanelButton(coordinator, pid, desc)
        for pid in coordinator.data
        for desc in BUTTONS
    )


class PanelButton(PanelEntity, ButtonEntity):
    def __init__(self, coordinator, panel_id, description) -> None:
        super().__init__(coordinator, panel_id, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        try:
            result = await self.coordinator.server.action(
                self._panel_id, self.entity_description.key
            )
        except PanelServerError as err:
            raise HomeAssistantError(str(err)) from err
        # The server reports whether the panel was actually reachable. Silence
        # on a button that did nothing is worse than an error, because the next
        # step is a walk to the wall to find out.
        if isinstance(result, dict) and result.get("sent") is False:
            raise HomeAssistantError(
                f"{self.entity_description.key} not delivered: the panel has no "
                "live connection to the server right now"
            )
        await self.coordinator.async_request_refresh()
