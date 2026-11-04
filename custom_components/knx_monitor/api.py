"""Client for the KNX Monitor add-on (endpoints below /api/ha/)."""

from __future__ import annotations

from typing import Any

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=15)
# Exports read weeks of history on the add-on.
EXPORT_TIMEOUT = aiohttp.ClientTimeout(total=600)


class KnxMonitorError(Exception):
    """The add-on did not answer or refused."""


class KnxMonitorAuthError(KnxMonitorError):
    """The token was rejected (add-on reinstalled)."""


class KnxMonitorApi:
    """Talks to the add-on with the token from its discovery.

    The add-on runs in the host network: Home Assistant reaches it under the
    add-on's host name, otherwise on 127.0.0.1. The first address that answers
    is kept.
    """

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token: str) -> None:
        self._session = session
        self._hosts = [host] if host in ("127.0.0.1", "localhost") else [host, "127.0.0.1"]
        self._port = port
        self._token = token
        self._base: str | None = None

    @property
    def base(self) -> str | None:
        """Address that answered last, for diagnostics."""
        return self._base

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout: aiohttp.ClientTimeout = TIMEOUT,
        raw: bool = False,
    ) -> Any:
        bases = [self._base] if self._base else [f"http://{h}:{self._port}" for h in self._hosts]
        headers = {"Authorization": f"Bearer {self._token}"}
        last: Exception | None = None
        for base in bases:
            try:
                async with self._session.request(
                    method, f"{base}{path}", json=json, params=params, headers=headers, timeout=timeout
                ) as resp:
                    if resp.status in (401, 403):
                        raise KnxMonitorAuthError(f"HTTP {resp.status}")
                    if resp.status >= 300:
                        raise KnxMonitorError(f"HTTP {resp.status}")
                    self._base = base
                    if raw:
                        return await resp.read(), resp.headers.get("Content-Disposition", "")
                    return await resp.json(content_type=None)
            except KnxMonitorAuthError:
                raise
            except (TimeoutError, aiohttp.ClientError, KnxMonitorError) as err:
                last = err
        # Address no longer answers (add-on moved): try all again next time.
        self._base = None
        raise KnxMonitorError(str(last) if last else "no address")

    async def state(self) -> dict[str, Any]:
        """Key figures, connection state and version."""
        return await self._request("GET", "/api/ha/state")

    async def set_recording(self, on: bool) -> dict[str, Any]:
        """Continuous recording on or off; returns the new state."""
        return await self._request("POST", "/api/ha/recording", json={"on": on})

    async def create_report(self) -> dict[str, Any]:
        """Creates the installation report now."""
        return await self._request("POST", "/api/ha/report")

    async def history(self, days: int | None) -> tuple[bytes, str]:
        """History as ETS file: the last `days` days, or everything as zip."""
        params = {"all": "1"} if days is None else {"days": str(days)}
        return await self._request("GET", "/api/ha/history", params=params, timeout=EXPORT_TIMEOUT, raw=True)

    async def diagnostics(self) -> dict[str, Any]:
        """Connection, storage and restarts, without names or values."""
        return await self._request("GET", "/api/ha/diagnostics")

    async def claim(self, on: bool) -> None:
        """Takes over the entities from the MQTT device, or gives them back."""
        await self._request("POST" if on else "DELETE", "/api/ha/claim")
