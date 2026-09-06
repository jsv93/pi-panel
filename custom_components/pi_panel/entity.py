"""Common base: one Home Assistant device per panel."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PanelCoordinator


class PanelEntity(CoordinatorEntity[PanelCoordinator]):
    """Anything belonging to one panel."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: PanelCoordinator, panel_id: str, key: str) -> None:
        super().__init__(coordinator)
        self._panel_id = panel_id
        # The server issues panel ids and a panel keeps its own forever, which
        # is what makes this safe to key entities on. Hostnames were tried
        # first and renaming a panel orphaned its record.
        self._attr_unique_id = f"{panel_id}_{key}"

    @property
    def panel(self) -> dict:
        return self.coordinator.data.get(self._panel_id) or {}

    @property
    def metrics(self) -> dict:
        return self.panel.get("metrics") or {}

    @property
    def available(self) -> bool:
        # The panel's own online flag is deliberately not part of this. A panel
        # that is switched off should read "offline", not vanish into
        # unavailable, or the fleet page in Home Assistant goes blank exactly
        # when someone is trying to find out why.
        return self.coordinator.last_update_success and self._panel_id in (
            self.coordinator.data or {}
        )

    @property
    def device_info(self) -> DeviceInfo:
        p = self.panel
        return DeviceInfo(
            identifiers={(DOMAIN, self._panel_id)},
            name=p.get("room") or p.get("hostname") or self._panel_id,
            manufacturer="Raspberry Pi",
            model=f"{p.get('kind', 'pi')} panel",
            sw_version=(p.get("metrics") or {}).get("ui_version"),
            configuration_url=None,
        )
