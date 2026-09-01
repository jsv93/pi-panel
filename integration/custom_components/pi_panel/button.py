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
    # Not diagnostic or config: "which of these is the study one" is a question
    # you ask standing in a hallway, so it belongs on the main card.
    ButtonEntityDescription(key="identify", translation_key="identify"),
    # Not diagnostic: this is meant to be driven by an automation -- presence,
    # a door contact, a motion sensor -- so the panel is awake before anyone
    # has reached it.
    ButtonEntityDescription(key="wake", translation_key="wake"),
    # Its counterpart, and on the main card for the same reason: a goodnight
    # scene that leaves every panel lit has not finished. Sleeping honours the
    # panel's own blank-after setting rather than forcing the screen black, so
    # a panel deliberately left showing a clock keeps showing one.
    ButtonEntityDescription(key="sleep", translation_key="sleep"),
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
