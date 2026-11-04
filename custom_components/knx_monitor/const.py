"""Constants of the KNX Monitor integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "knx_monitor"
MANUFACTURER: Final = "regetskcob"

CONF_TOKEN: Final = "token"
CONF_SLUG: Final = "slug"

# Same names as the add-on's events (ha.dart).
EVENT_WATCHER: Final = "knx_monitor_watcher"
EVENT_ALARM: Final = "knx_monitor_alarm"
EVENT_BUS: Final = "knx_monitor_bus"

SCAN_INTERVAL: Final = timedelta(seconds=30)

# A repair is raised once the bus has been gone this long.
BUS_LOST_REPAIR_AFTER: Final = timedelta(minutes=10)

SERVICE_CREATE_REPORT: Final = "create_report"
SERVICE_EXPORT_HISTORY: Final = "export_history"
