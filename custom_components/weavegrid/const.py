"""Constants for the WeaveGrid integration."""

from __future__ import annotations

DOMAIN = "weavegrid"

DEFAULT_BASE_URL = "https://charge.weavegrid.com"
DEFAULT_UTILITY = "bge"
DEFAULT_SCAN_INTERVAL = 5  # minutes

CONF_UTILITY = "utility_acronym"
CONF_AUTH_METHOD = "auth_method"
CONF_SESSION_COOKIE = "session_cookie"
CONF_INCLUDE_ARCHIVED = "include_archived"
CONF_SCAN_INTERVAL = "scan_interval"

AUTH_METHOD_PASSWORD = "password"
AUTH_METHOD_MAGIC_LINK = "magic_link"
AUTH_METHOD_COOKIE = "session_cookie"

# Human-readable labels for WeaveGrid's deviceStatusContentKey values
STATUS_KEY_LABELS: dict[str, str] = {
    "unplugged": "Unplugged",
    "ready": "Ready",
    "ready_evse": "Ready",
    "scheduled_single_segment": "Scheduled",
    "scheduled_single_segment_evse": "Scheduled",
    "scheduled_multi_segment": "Scheduled (Multi-Window)",
    "scheduled_multi_segment_evse": "Scheduled (Multi-Window)",
    "plugged_in_scheduled_v2": "Scheduled",
    "plugged_in_scheduled_v2_evse": "Scheduled",
    "plugged_in_charging_from_schedule_v2": "Smart Charging",
    "plugged_in_charging_from_schedule_v2_evse": "Smart Charging",
    "plugged_in_charging_from_schedule_v2_last_segment": "Smart Charging",
    "plugged_in_charging_from_schedule_v2_evse_last_segment": "Smart Charging",
    "plugged_in_charging_not_from_schedule": "Charging (Override)",
    "plugged_in_charging_low_soc": "Charging (Low Battery)",
    "plugged_in_diverged": "Plugged In (Diverged)",
    "plugged_in_not_charging": "Plugged In (Idle)",
    "plugged_in_not_charging_no_schedule": "Plugged In (No Schedule)",
}


def format_status_key(raw_key: str | None) -> str:
    """Convert WeaveGrid deviceStatusContentKey into a clean status string."""
    if not raw_key:
        return "Unknown"
    if raw_key in STATUS_KEY_LABELS:
        return STATUS_KEY_LABELS[raw_key]
    cleaned = raw_key.removesuffix("_evse").replace("_", " ").strip()
    return cleaned.title() if cleaned else "Unknown"
