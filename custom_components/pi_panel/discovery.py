"""Discover new fleet entities and provisioned Bluetooth receivers at runtime."""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import time

from homeassistant.config_entries import SOURCE_IGNORE, SOURCE_USER
from homeassistant.helpers import area_registry as ar, device_registry as dr

_LOGGER = logging.getLogger(__name__)


def watch_panels(entry, add, factory):
    """Each platform adds each ID once, including panels arriving after startup."""
    coordinator = entry.runtime_data
    known = set()

    def update():
        new = set(coordinator.data or {}) - known
        if new:
            entities = [entity for pid in sorted(new) for entity in factory(pid)]
            add(entities)
            known.update(new)

    entry.async_on_unload(coordinator.async_add_listener(update))
    update()


def scanner_candidate(panel):
    metrics = panel.get("metrics") or {}
    if not (panel.get("claimed") and panel.get("kind") == "pi" and panel.get("online")
            and metrics.get("bluetooth_managed") is True
            and metrics.get("bluetooth_active") is True):
        return None
    if time.time() - metrics.get("bluetooth_sample_at", 0) > 90:
        return None
    mac = str(metrics.get("bluetooth_mac", "")).lower()
    if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", mac) or mac == "00:00:00:00:00:00":
        return None
    try:
        host = ipaddress.ip_address(panel.get("ip", ""))
    except ValueError:
        return None
    if not host.is_private or host.is_loopback or host.is_unspecified or host.is_multicast:
        return None
    return str(host), mac


class ScannerEnrollment:
    """Only opt-in receivers installed by the provisioning script are enrolled.

    Ordinary/legacy ESPHome devices, ignored entries and existing options are
    left alone. HA's config flow validates the connection and deduplicates by MAC.
    """

    def __init__(self, hass, coordinator):
        self.hass = hass
        self.coordinator = coordinator
        self.retry_at = {}
        self.done = set()
        self.created = set()

    def assign_area(self, entry, panel):
        room = str(panel.get("room") or "").casefold()
        areas = ar.async_get(self.hass)
        matches = [area for area in areas.async_list_areas()
                   if room in (area.id.casefold(), area.name.casefold())]
        if len(matches) != 1:
            return True  # No guess: the operator can assign an area in HA.
        registry = dr.async_get(self.hass)
        devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
        for device in devices:
            if not device.area_id:
                registry.async_update_device(device.id, area_id=matches[0].id)
        return bool(devices)

    async def enroll(self, panel):
        candidate = scanner_candidate(panel)
        if not candidate:
            return
        host, mac = candidate
        if mac in self.done or time.monotonic() < self.retry_at.get(mac, 0):
            return
        self.retry_at[mac] = time.monotonic() + 300
        entries = self.hass.config_entries.async_entries("esphome")
        existing = next((entry for entry in entries if str(entry.unique_id).lower() == mac), None)
        if existing:
            if mac in self.created and existing.source != SOURCE_IGNORE:
                if not self.assign_area(existing, panel):
                    self.retry_at[mac] = time.monotonic() + 30
                    return
            self.done.add(mac)
            return
        flow_id = None
        try:
            result = await self.hass.config_entries.flow.async_init(
                "esphome", context={"source": SOURCE_USER})
            flow_id = result.get("flow_id")
            if result["type"] == "form" and result.get("step_id") == "user":
                result = await self.hass.config_entries.flow.async_configure(
                    flow_id, user_input={"host": host, "port": 6053})
            if result["type"] == "create_entry":
                entry = result["result"]
                # BlueZ on Pi OS does not consistently support passive scanning.
                self.hass.config_entries.async_update_entry(entry, options={
                    **entry.options, "bluetooth_scanning_mode": "active",
                    "allow_service_calls": False, "subscribe_logs": False,
                })
                self.created.add(mac)
                self.retry_at[mac] = time.monotonic() + 30
                _LOGGER.info("Enrolled Bluetooth scanner for panel %s", panel["id"])
            elif result["type"] == "abort" and result.get("reason") == "already_configured":
                self.done.add(mac)
            else:
                _LOGGER.warning("Scanner enrollment for %s awaits HA: %s", panel["id"],
                                result.get("errors") or result.get("reason") or result.get("step_id"))
        finally:
            # Never leave a shelf of failed forms behind during network outages.
            if flow_id and any(flow["flow_id"] == flow_id
                               for flow in self.hass.config_entries.flow.async_progress()):
                self.hass.config_entries.flow.async_abort(flow_id)

    async def run(self):
        while True:
            for panel in list((self.coordinator.data or {}).values()):
                try:
                    await asyncio.wait_for(self.enroll(panel), timeout=45)
                except Exception as error:
                    _LOGGER.warning("Scanner enrollment for %s will retry: %s",
                                    panel.get("id"), type(error).__name__)
            await asyncio.sleep(30)
