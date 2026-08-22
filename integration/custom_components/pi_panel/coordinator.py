"""Talks to the config server and holds the fleet's state for the entities.

Read-heavy by design. Home Assistant is never in the path of a panel getting
its config -- panels pull that from the server themselves -- so everything here
can fail, or Home Assistant can be down entirely, without a panel noticing.
"""
from __future__ import annotations

import logging
from datetime import timedelta

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CLIENT_HEADER, CLIENT_NAME, OWNER_HA, SCAN_INTERVAL_S

_LOGGER = logging.getLogger(__name__)


class PanelServerError(Exception):
    """The server answered, but not with what was asked for."""


class NotTheOwner(PanelServerError):
    """Refused because the server's config_owner is not Home Assistant.

    Its own class because it is the one failure here that is a correct answer
    rather than a fault: the operator has chosen the server as the source of
    truth, and this is that choice being kept.
    """


class PanelServer:
    """Thin client. Sessions are cookie-based, so it re-authenticates on 401."""

    def __init__(self, hass: HomeAssistant, host: str, port: int, password: str) -> None:
        # Its own session, not Home Assistant's shared one: the server
        # authenticates with a cookie, and the shared session discards cookies
        # outright.
        #
        # unsafe=True is not optional. aiohttp's default jar refuses to store
        # cookies from a host that is a bare IP address, and the address wanted
        # here is the one panels use -- which is an IP. Without it the login
        # succeeds, the cookie is dropped on the floor, the next request 401s,
        # and the retry does the same thing forever. It fails as "password
        # rejected" while the password is perfectly correct.
        self._session = async_create_clientsession(
            hass, cookie_jar=aiohttp.CookieJar(unsafe=True)
        )
        self._base = f"http://{host}:{port}"
        self._password = password

    async def _login(self) -> None:
        try:
            async with self._session.post(
                f"{self._base}/api/login", json={"password": self._password}
            ) as r:
                if r.status == 401:
                    raise ConfigEntryAuthFailed("password rejected by the panel server")
                r.raise_for_status()
        except aiohttp.ClientError as err:
            raise PanelServerError(f"cannot reach {self._base}: {err}") from err

    async def _request(self, method: str, path: str, *, json=None, retry=True):
        headers = {CLIENT_HEADER: CLIENT_NAME}
        try:
            async with self._session.request(
                method, f"{self._base}/api{path}", json=json, headers=headers
            ) as r:
                if r.status == 401 and retry:
                    # The session expired rather than the password being wrong.
                    await self._login()
                    return await self._request(method, path, json=json, retry=False)
                if r.status == 401:
                    raise ConfigEntryAuthFailed("password rejected by the panel server")
                if r.status == 409:
                    body = await r.json()
                    raise NotTheOwner(body.get("detail", "config is owned elsewhere"))
                r.raise_for_status()
                if r.content_type == "application/json":
                    return await r.json()
                return await r.text()
        except aiohttp.ClientError as err:
            raise PanelServerError(f"{method} {path} failed: {err}") from err

    async def panels(self):
        return await self._request("GET", "/panels")

    async def settings(self):
        return await self._request("GET", "/settings")

    async def action(self, panel_id: str, action: str):
        return await self._request(
            "POST", f"/panels/{panel_id}/action", json={"action": action}
        )

    async def put_config(self, panel_id: str, config: dict):
        """Raises NotTheOwner unless the server has handed config to us.

        Kept here, unused by any entity today, so the ownership rule lives in
        one place when something does start writing.
        """
        return await self._request("PUT", f"/panels/{panel_id}/config", json=config)


class PanelCoordinator(DataUpdateCoordinator):
    """Polls the fleet. One request covers every panel."""

    def __init__(self, hass: HomeAssistant, server: PanelServer) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="pi_panel",
            update_interval=timedelta(seconds=SCAN_INTERVAL_S),
        )
        self.server = server
        self.config_owner: str = "server"

    @property
    def ha_owns_config(self) -> bool:
        return self.config_owner == OWNER_HA

    async def _async_update_data(self):
        try:
            panels = await self.server.panels()
            # Fetched every cycle rather than once at setup: the operator can
            # move ownership in the server's GUI at any time, and an
            # integration that believed a stale answer would offer writes that
            # the server then refuses.
            try:
                self.config_owner = (await self.server.settings()).get(
                    "config_owner", "server"
                )
            except PanelServerError:
                pass
            return {p["id"]: p for p in panels}
        except ConfigEntryAuthFailed:
            raise
        except PanelServerError as err:
            raise UpdateFailed(str(err)) from err
