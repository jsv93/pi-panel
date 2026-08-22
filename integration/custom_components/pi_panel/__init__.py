"""Pi Panel — Home Assistant view of the wall panel fleet.

Reads the config server, which is the source of truth for what a panel shows.
Nothing here is required for a panel to work: panels pull their config from the
server directly and run from a cached copy if the server is unreachable, so
this integration being down, or Home Assistant being down, costs visibility and
nothing else.
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .coordinator import PanelCoordinator, PanelServer

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR]

# Plain alias rather than a `type` statement: identical here, and it keeps the
# file parseable by anything older than 3.12, which is what checks it outside
# Home Assistant.
PiPanelEntry = ConfigEntry[PanelCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: PiPanelEntry) -> bool:
    server = PanelServer(
        hass,
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_PASSWORD],
    )
    coordinator = PanelCoordinator(hass, server)
    # Raises and aborts setup if the server cannot be reached, rather than
    # creating a shelf of unavailable entities that look like broken panels.
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PiPanelEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
