"""Client for the KNX Monitor add-on (endpoints below /api/ha/)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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

    Only the address the add-on announced gets the token. There is no fallback
    to 127.0.0.1: if the add-on's host name does not resolve, whatever else
    listens on that port of the host would receive the bearer token. The add-on
    announces 127.0.0.1 itself when it has no host name.
    """

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token: str) -> None:
        self._session = session
        self._url = f"http://{host}:{port}"
        self._token = token
        self._base: str | None = None

    @property
    def base(self) -> str | None:
        """Address that answered last, for diagnostics."""
        return self._base

    @asynccontextmanager
    async def _open(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        timeout: aiohttp.ClientTimeout = TIMEOUT,
    ) -> AsyncIterator[aiohttp.ClientResponse]:
        """Response of the add-on with a checked status, open while in the block."""
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            async with self._session.request(
                method, f"{self._url}{path}", json=json, params=params, headers=headers, timeout=timeout
            ) as resp:
                if resp.status in (401, 403):
                    raise KnxMonitorAuthError(f"HTTP {resp.status}")
                if resp.status >= 300:
                    raise KnxMonitorError(f"HTTP {resp.status}")
                self._base = self._url
                yield resp
        except KnxMonitorError:
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            raise KnxMonitorError(str(err) or type(err).__name__) from err

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        async with self._open(method, path, **kwargs) as resp:
            return await resp.json(content_type=None)

    async def state(self) -> dict[str, Any]:
        """Key figures, connection state and version."""
        return await self._request("GET", "/api/ha/state")

    async def set_recording(self, on: bool) -> dict[str, Any]:
        """Continuous recording on or off; returns the new state."""
        return await self._request("POST", "/api/ha/recording", json={"on": on})

    async def create_report(self) -> dict[str, Any]:
        """Creates the installation report now."""
        return await self._request("POST", "/api/ha/report")

    @asynccontextmanager
    async def history(self, days: int | None) -> AsyncIterator[aiohttp.ClientResponse]:
        """History as ETS file: the last `days` days, or everything as zip.

        Yields the open response so the caller can stream the body to disk
        instead of holding a zip of the whole history in memory.
        """
        params = {"all": "1"} if days is None else {"days": str(days)}
        async with self._open("GET", "/api/ha/history", params=params, timeout=EXPORT_TIMEOUT) as resp:
            yield resp

    async def diagnostics(self) -> dict[str, Any]:
        """Connection, storage and restarts, without names or values."""
        return await self._request("GET", "/api/ha/diagnostics")

    async def claim(self, on: bool) -> None:
        """Takes over the entities from the MQTT device, or gives them back."""
        await self._request("POST" if on else "DELETE", "/api/ha/claim")
