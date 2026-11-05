"""DataUpdateCoordinator for WeaveGrid."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    WeaveGridAccountData,
    WeaveGridApiClient,
    WeaveGridAuthExpired,
    WeaveGridError,
    WeaveGridInvalidAuth,
    WeaveGridTwoFactorRequired,
)
from .const import (
    CONF_INCLUDE_ARCHIVED,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_COOKIE,
    CONF_UTILITY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class WeaveGridCoordinator(DataUpdateCoordinator[WeaveGridAccountData]):
    """Coordinator managing polling and auto-reauthentication for WeaveGrid."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: WeaveGridApiClient,
    ) -> None:
        self.client = client
        interval_min = int(
            entry.options.get(
                CONF_SCAN_INTERVAL,
                entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            config_entry=entry,
            update_interval=timedelta(minutes=max(1, interval_min)),
        )

    @property
    def include_archived(self) -> bool:
        """Whether archived registrations should be exposed as devices."""
        return bool(
            self.config_entry.options.get(
                CONF_INCLUDE_ARCHIVED,
                self.config_entry.data.get(CONF_INCLUDE_ARCHIVED, False),
            )
        )

    async def _async_relogin_if_possible(self) -> None:
        """Attempt background password re-login when session cookie expires."""
        email = self.config_entry.data.get(CONF_EMAIL)
        password = self.config_entry.data.get(CONF_PASSWORD)
        if not email or not password:
            raise ConfigEntryAuthFailed(
                "WeaveGrid session expired. Please reauthenticate."
            )

        try:
            _LOGGER.debug("Refreshing expired WeaveGrid session for %s", email)
            await self.client.async_login(email, password)
        except (WeaveGridInvalidAuth, WeaveGridTwoFactorRequired) as err:
            raise ConfigEntryAuthFailed(
                f"WeaveGrid credentials require reauthentication: {err}"
            ) from err
        except WeaveGridError as err:
            raise UpdateFailed(f"Error refreshing WeaveGrid login: {err}") from err

        self._persist_cookie_if_changed()

    def _persist_cookie_if_changed(self) -> None:
        """Save latest session cookie and discovered utility acronym in config entry."""
        new_cookie = self.client.get_session_cookie()
        current_cookie = self.config_entry.data.get(CONF_SESSION_COOKIE)
        current_util = self.config_entry.data.get(CONF_UTILITY)
        if new_cookie and (
            new_cookie != current_cookie or self.client.utility_acronym != current_util
        ):
            new_data = {
                **self.config_entry.data,
                CONF_SESSION_COOKIE: new_cookie,
                CONF_UTILITY: self.client.utility_acronym,
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )

    async def _async_update_data(self) -> WeaveGridAccountData:
        """Fetch latest state for all WeaveGrid vehicles/chargers."""
        if not self.client.get_session_cookie():
            await self._async_relogin_if_possible()

        try:
            data = await self.client.async_fetch_all(
                include_archived=self.include_archived
            )
        except WeaveGridAuthExpired:
            await self._async_relogin_if_possible()
            try:
                data = await self.client.async_fetch_all(
                    include_archived=self.include_archived
                )
            except WeaveGridAuthExpired as err:
                raise ConfigEntryAuthFailed(
                    "WeaveGrid session still invalid after re-login"
                ) from err
            except WeaveGridError as err:
                raise UpdateFailed(f"Error communicating with WeaveGrid: {err}") from err
        except WeaveGridError as err:
            raise UpdateFailed(f"Error communicating with WeaveGrid: {err}") from err

        self._persist_cookie_if_changed()
        return data

    async def async_trigger_charge_now(self, vehicle_id: str) -> None:
        """Send Charge Now override and refresh state after WeaveGrid re-optimizes."""
        try:
            await self.client.async_charge_now(vehicle_id)
        except WeaveGridAuthExpired:
            await self._async_relogin_if_possible()
            await self.client.async_charge_now(vehicle_id)
        except WeaveGridError as err:
            raise HomeAssistantError(f"Charge Now failed: {err}") from err

        # WeaveGrid's portal waits 2s for plan re-optimization before reloading
        await asyncio.sleep(2)
        await self.async_request_refresh()

    async def async_set_peak_avoidance(
        self, vehicle_id: str, enabled: bool
    ) -> dict[str, Any]:
        """Update Peak Avoidance setting and refresh coordinator."""
        veh = (self.data.vehicles.get(vehicle_id)) if self.data else None
        current_mc = veh.mc_settings if veh else None
        try:
            res = await self.client.async_set_peak_avoidance(
                vehicle_id, enabled, current_mc
            )
        except WeaveGridAuthExpired:
            await self._async_relogin_if_possible()
            res = await self.client.async_set_peak_avoidance(
                vehicle_id, enabled, current_mc
            )
        except WeaveGridError as err:
            raise HomeAssistantError(f"Updating Peak Avoidance failed: {err}") from err

        if veh is not None and res:
            veh.mc_settings = res
        await self.async_request_refresh()
        return res
