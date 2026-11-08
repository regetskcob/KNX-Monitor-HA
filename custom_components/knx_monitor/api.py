"""Client for the Busclear server (endpoints below /api/ha/)."""

from __future__ import annotations

import base64
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
    """The token was rejected (add-on reinstalled, box device revoked or without admin rights)."""


class KnxMonitorNotFoundError(KnxMonitorError):
    """The endpoint does not exist (older add-on) or the item is gone."""


class KnxMonitorTlsError(KnxMonitorError):
    """The server's certificate does not match the fingerprint from the pairing link."""


def fingerprint_bytes(fingerprint: str) -> bytes:
    """SHA-256 from the pairing link (`fp`, base64url without padding) as bytes."""
    raw = base64.urlsafe_b64decode(fingerprint + "=" * (-len(fingerprint) % 4))
    if len(raw) != 32:
        raise ValueError("not a SHA-256 fingerprint")
    return raw


class KnxMonitorApi:
    """Talks to the Busclear server with its token.

    Only the configured address gets the token: the one the add-on announced,
    or the one entered for a KNX box. There is no fallback to 127.0.0.1: if
    the add-on's host name does not resolve, whatever else listens on that port
    of the host would receive the bearer token. The add-on announces 127.0.0.1
    itself when it has no host name. Redirects are not followed, so the token
    cannot be passed on to another address either.

    With a [fingerprint] (KNX box with its own certificate) the connection is
    HTTPS and trusts exactly that certificate, nothing else.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        token: str,
        *,
        ssl: bool = False,
        fingerprint: str | None = None,
    ) -> None:
        self._session = session
        secure = ssl or fingerprint is not None
        # An IPv6 address needs brackets in the URL.
        name = f"[{host}]" if ":" in host and not host.startswith("[") else host
        self._url = f"{'https' if secure else 'http'}://{name}:{port}"
        self._token = token
        self._ssl: aiohttp.Fingerprint | bool = (
            aiohttp.Fingerprint(fingerprint_bytes(fingerprint)) if fingerprint else True
        )
        self._base: str | None = None

    @property
    def url(self) -> str:
        """Base address, e.g. for the device's configuration URL."""
        return self._url

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
                method,
                f"{self._url}{path}",
                json=json,
                params=params,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                ssl=self._ssl,
            ) as resp:
                if resp.status in (401, 403):
                    raise KnxMonitorAuthError(f"HTTP {resp.status}")
                if resp.status == 404:
                    raise KnxMonitorNotFoundError(f"HTTP {resp.status}")
                if resp.status >= 300:
                    raise KnxMonitorError(f"HTTP {resp.status}")
                self._base = self._url
                yield resp
        except KnxMonitorError:
            raise
        except aiohttp.ServerFingerprintMismatch as err:
            raise KnxMonitorTlsError(str(err)) from err
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

    async def watchers(self) -> dict[str, str]:
        """Watchers by id with their names; KnxMonitorNotFoundError on add-ons before 1.9.10."""
        rules = await self._request("GET", "/api/ha/watchers")
        return {
            str(r["id"]): str(r.get("name") or r["id"])
            for r in rules
            if isinstance(r, dict) and isinstance(r.get("id"), str)
        }

    async def silent(self) -> list[dict[str, Any]]:
        """Addresses that stopped sending, oldest silence first (at most 20)."""
        result = await self._request("GET", "/api/ha/silent")
        return [s for s in result if isinstance(s, dict) and isinstance(s.get("address"), str)]

    async def ignore_silent(self, address: str) -> None:
        """No longer reports `address` until it sends again."""
        await self._request("POST", "/api/ha/silent/ignore", json={"address": address})
