"""Setup of Busclear: through the add-on's discovery, or by hand for a KNX box or container."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.hassio import is_hassio
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .api import KnxMonitorApi, KnxMonitorAuthError, KnxMonitorError, KnxMonitorTlsError
from .const import CONF_FINGERPRINT, CONF_SLUG, CONF_SSL, CONF_TOKEN, DOMAIN

CONF_ADDRESS = "address"
CONF_LINK = "link"

# Slug of the Busclear add-on: from the official repository (the
# Supervisor's prefix is the first 8 hex digits of the SHA-1 of the lower-case
# repository URL, https://github.com/regetskcob/knx-monitor) or from the local
# add-on folder. Any other repository could pick a slug like
# `deadbeef_knx_monitor` and receive the token.
ADDON_SLUG = re.compile(r"(?:2541da37|local)_knx_monitor")


def is_knx_monitor_addon(slug: str | None) -> bool:
    """Whether the announcing add-on is Busclear.

    The Supervisor puts the slug of the add-on that posted a discovery message
    into it, so another add-on cannot pretend to be Busclear. Accepted are
    the add-on from the official repository (`2541da37_knx_monitor`) and the
    local build (`local_knx_monitor`), not the same name from another
    repository nor an add-on whose own slug merely ends in `_knx_monitor`. Every other add-on announcing the
    service `knx_monitor` would otherwise redirect the token and the entities
    to itself.
    """
    return bool(slug) and ADDON_SLUG.fullmatch(slug) is not None


# As the app reads the pairing link (lib/platform/box_link.dart).
_KEY = re.compile(r"[A-Za-z0-9_~.-]{1,128}")
_FINGERPRINT = re.compile(r"[A-Za-z0-9_-]{43}")
_HOST = re.compile(r"[A-Za-z0-9.-]{1,253}|\[[0-9A-Fa-f:.]{2,45}\]")


@dataclass(frozen=True)
class Target:
    """Where the token goes: scheme, host and port, plus the pinned certificate."""

    host: str
    port: int
    ssl: bool
    fingerprint: str | None


def _address(text: str) -> tuple[str | None, str, int | None] | None:
    """Scheme (if given), host and port (if given) of an address like `knx-box.local:8765`."""
    text = text.strip()
    if not text:
        return None
    parts = urlsplit(text if "://" in text else f"//{text}")
    if parts.scheme not in ("", "http", "https") or parts.username or parts.password:
        return None
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    host = parts.netloc.rsplit("@", 1)[-1]
    host = host[: host.rfind(":")] if port is not None else host
    if not _HOST.fullmatch(host):
        return None
    return parts.scheme or None, host.strip("[]"), port


def parse_pairing(link: str, address: str = "") -> tuple[Target, str] | None:
    """Target and device key from the box's pairing link and an optional address.

    The link (`knxmonitor://box?url=…&key=…&fp=…`, shown under /pair) brings
    the key and, with the box's own certificate, its fingerprint; the address,
    if given, replaces host and port from the link (the link may name the box
    Wi-Fi address, Home Assistant reaches the box in the home network). With a
    fingerprint the connection is always HTTPS: on the port of an `https://`
    address or link, otherwise 443, as the box serves it. `None` if the link
    or the address is not valid.
    """
    parts = urlsplit(link.strip())
    if parts.scheme != "knxmonitor" or parts.netloc != "box":
        return None
    query = {k: v[0] for k, v in parse_qs(parts.query).items() if v}
    key = query.get("key", "")
    fingerprint = query.get("fp") or None
    if not _KEY.fullmatch(key) or (fingerprint is not None and not _FINGERPRINT.fullmatch(fingerprint)):
        return None
    from_link = _address(query.get("url", ""))
    if from_link is None or from_link[0] is None:
        return None
    link_scheme, host, link_port = from_link
    scheme, port = link_scheme, link_port
    if address.strip():
        given = _address(address)
        if given is None:
            return None
        given_scheme, host, given_port = given
        if given_scheme is not None or given_port is not None:
            scheme, port = given_scheme or "http", given_port
    if fingerprint is not None:
        # Never downgrade below the link: the certificate is pinned over HTTPS.
        if scheme != "https":
            port = link_port if link_scheme == "https" else None
        return Target(host, port or 443, True, fingerprint), key
    ssl = scheme == "https"
    return Target(host, port or (443 if ssl else 80), ssl, None), key


class KnxMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """The add-on announces host, port and token; the user only confirms.

    Without the add-on (Home Assistant Container, or Busclear on a KNX box
    or in Docker), the user enters the box's address and pairing link.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Added by hand: take the running add-on's announcement, otherwise a KNX box or container."""
        if not is_hassio(self.hass):
            return await self.async_step_manual()
        try:
            from homeassistant.components.hassio import get_supervisor_client

            messages = await get_supervisor_client(self.hass).discovery.list()
        except Exception:  # noqa: BLE001 - Supervisor not ready or too old: set up by hand
            return await self.async_step_manual()
        message = next((m for m in messages if m.service == DOMAIN and is_knx_monitor_addon(m.addon)), None)
        if message is None:
            return await self.async_step_manual()
        return await self._discovered(message.config, message.addon)

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """KNX box or Docker container: address and pairing link of a device with admin rights."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        errors: dict[str, str] = {}
        if user_input is not None:
            parsed = parse_pairing(user_input.get(CONF_LINK, ""), user_input.get(CONF_ADDRESS, ""))
            if parsed is None:
                errors["base"] = "invalid_link"
            else:
                target, key = parsed
                api = KnxMonitorApi(
                    async_get_clientsession(self.hass),
                    target.host,
                    target.port,
                    key,
                    ssl=target.ssl,
                    fingerprint=target.fingerprint,
                )
                try:
                    await api.state()
                except KnxMonitorTlsError:
                    errors["base"] = "tls_mismatch"
                except KnxMonitorAuthError:
                    errors["base"] = "invalid_auth"
                except KnxMonitorError:
                    errors["base"] = "box_unreachable"
                else:
                    data: dict[str, Any] = {
                        CONF_HOST: target.host,
                        CONF_PORT: target.port,
                        CONF_TOKEN: key,
                        CONF_SSL: target.ssl,
                    }
                    if target.fingerprint:
                        data[CONF_FINGERPRINT] = target.fingerprint
                    return self.async_create_entry(title="Busclear", data=data)
        schema = vol.Schema(
            {
                vol.Optional(CONF_ADDRESS, default=(user_input or {}).get(CONF_ADDRESS, "")): str,
                # The key is not shown again after a failed attempt.
                vol.Required(CONF_LINK): str,
            }
        )
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """The Busclear add-on announced itself."""
        if not is_knx_monitor_addon(discovery_info.slug):
            return self.async_abort(reason="not_knx_monitor_addon")
        return await self._discovered(discovery_info.config, discovery_info.slug)

    async def _discovered(self, config: dict[str, Any], slug: str) -> ConfigFlowResult:
        self._discovery = {
            CONF_HOST: config["host"],
            CONF_PORT: int(config["port"]),
            CONF_TOKEN: config["token"],
            # Add-on slug with the repository prefix, for the link to its panel.
            CONF_SLUG: slug,
        }
        await self.async_set_unique_id(DOMAIN)
        # Set up by hand for a KNX box: the add-on does not take that entry over.
        existing = self.hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, DOMAIN)
        if existing is not None and CONF_SLUG not in existing.data:
            return self.async_abort(reason="already_configured")
        # Add-on reinstalled (new token) or moved: update the existing entry.
        self._abort_if_unique_id_configured(updates=self._discovery)
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask once, then check that the add-on answers."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api = KnxMonitorApi(
                async_get_clientsession(self.hass),
                self._discovery[CONF_HOST],
                self._discovery[CONF_PORT],
                self._discovery[CONF_TOKEN],
            )
            try:
                await api.state()
            except KnxMonitorError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Busclear", data=self._discovery)
        return self.async_show_form(step_id="hassio_confirm", errors=errors)
