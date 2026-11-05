"""The WeaveGrid integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import WeaveGridApiClient
from .const import CONF_SESSION_COOKIE, CONF_UTILITY, DEFAULT_UTILITY, DOMAIN
from .coordinator import WeaveGridCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WeaveGrid from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = WeaveGridApiClient(
        utility_acronym=entry.data.get(CONF_UTILITY, DEFAULT_UTILITY),
        session_cookie=entry.data.get(CONF_SESSION_COOKIE),
    )
    coordinator = WeaveGridCoordinator(hass, entry, client)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.async_close()
        raise

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and close its isolated HTTP session."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: WeaveGridCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.async_close()
    return unload_ok
