"""Constants of the Busclear integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "knx_monitor"
MANUFACTURER: Final = "regetskcob"

CONF_TOKEN: Final = "token"
CONF_SLUG: Final = "slug"
# Set up by hand (Busclear Box or Docker, no Supervisor): HTTPS, and the SHA-256 of
# the server's certificate from the pairing link (base64url without padding).
CONF_SSL: Final = "ssl"
CONF_FINGERPRINT: Final = "fingerprint"

# Same names as the add-on's events (ha.dart).
EVENT_WATCHER: Final = "knx_monitor_watcher"
EVENT_ALARM: Final = "knx_monitor_alarm"
EVENT_BUS: Final = "knx_monitor_bus"

# Event channel of a Busclear Box or Docker container (no Supervisor), format
# version 1 (docs/event-channel.md in the development repository). The server
# says in `events` of /api/ha/state that it has the channel.
EVENTS_PATH: Final = "/ws/events"
EVENTS_FORMAT: Final = 1
# Events the integration fires itself from the event channel carry its entry;
# the add-on's own (through the Supervisor) do not.
ATTR_CONFIG_ENTRY_ID: Final = "config_entry_id"
# Seconds between attempts after the channel was lost, the last one repeats.
EVENTS_BACKOFF: Final = (1, 2, 5, 10, 30, 60)

SCAN_INTERVAL: Final = timedelta(seconds=30)

# A repair is raised once the bus has been gone this long.
BUS_LOST_REPAIR_AFTER: Final = timedelta(minutes=10)

# The watcher list (one device trigger per watcher) is reloaded this often,
# and after a watcher event with an unknown id at most this often.
WATCHERS_INTERVAL: Final = timedelta(minutes=10)
WATCHERS_RELOAD_MIN: Final = timedelta(minutes=1)

# From this many silent addresses on, one summary repair instead of one each.
SILENT_SUMMARY_FROM: Final = 5

SERVICE_CREATE_REPORT: Final = "create_report"
SERVICE_EXPORT_HISTORY: Final = "export_history"
SERVICE_RUN_HEALTH_CHECK: Final = "run_health_check"
