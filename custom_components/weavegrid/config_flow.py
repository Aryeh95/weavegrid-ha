"""Config flow for WeaveGrid integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback

from .api import (
    WeaveGridApiClient,
    WeaveGridAuthExpired,
    WeaveGridConnectionError,
    WeaveGridError,
    WeaveGridInvalidAuth,
    WeaveGridTwoFactorRequired,
)
from .const import (
    AUTH_METHOD_MAGIC_LINK,
    AUTH_METHOD_PASSWORD,
    CONF_AUTH_METHOD,
    CONF_INCLUDE_ARCHIVED,
    CONF_SCAN_INTERVAL,
    CONF_SESSION_COOKIE,
    CONF_UTILITY,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UTILITY,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class WeaveGridConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for WeaveGrid."""

    VERSION = 1

    def __init__(self) -> None:
        self._client: WeaveGridApiClient | None = None
        self._email: str = ""
        self._password: str = ""
        self._utility: str = DEFAULT_UTILITY
        self._reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return WeaveGridOptionsFlow()

    async def _async_finish_entry(self, auth_method: str) -> ConfigFlowResult:
        """Validate session, assign unique_id, and create or update the ConfigEntry."""
        assert self._client is not None
        viewer = await self._client.async_validate_session()
        user_id = str(viewer["userId"])
        session_cookie = self._client.get_session_cookie()
        utility = self._client.utility_acronym
        await self._client.async_close()
        self._client = None

        entry_data: dict[str, Any] = {
            CONF_EMAIL: self._email or viewer.get("email") or "",
            CONF_UTILITY: utility,
            CONF_AUTH_METHOD: auth_method,
            CONF_SESSION_COOKIE: session_cookie,
        }
        if self._password:
            entry_data[CONF_PASSWORD] = self._password

        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry,
                data_updates=entry_data,
            )

        await self.async_set_unique_id(f"weavegrid_{user_id}")
        self._abort_if_unique_id_configured()

        title = f"WeaveGrid ({utility.upper()} - {entry_data[CONF_EMAIL]})"
        return self.async_create_entry(title=title, data=entry_data)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle initial login step (Email + Password, or blank password for Magic Link)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip()
            self._password = (user_input.get(CONF_PASSWORD) or "").strip()
            self._utility = (
                user_input.get(CONF_UTILITY) or DEFAULT_UTILITY
            ).strip().lower()

            if self._client:
                await self._client.async_close()
            self._client = WeaveGridApiClient(utility_acronym=self._utility)

            try:
                if self._password:
                    await self._client.async_login(self._email, self._password)
                    return await self._async_finish_entry(AUTH_METHOD_PASSWORD)

                # No password entered -> send emailed magic link
                await self._client.async_request_magic_link(self._email)
                return await self.async_step_magic_link()
            except WeaveGridTwoFactorRequired:
                return await self.async_step_totp()
            except (WeaveGridInvalidAuth, WeaveGridAuthExpired):
                errors["base"] = "invalid_auth"
            except WeaveGridConnectionError:
                errors["base"] = "cannot_connect"
            except WeaveGridError as err:
                _LOGGER.exception("WeaveGrid setup error: %s", err)
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL, default=self._email): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
                vol.Required(CONF_UTILITY, default=self._utility): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_totp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle TOTP 2FA verification step."""
        errors: dict[str, str] = {}

        if user_input is not None and self._client is not None:
            try:
                await self._client.async_verify_totp(
                    self._email, user_input["totp_code"]
                )
                return await self._async_finish_entry(AUTH_METHOD_PASSWORD)
            except (WeaveGridInvalidAuth, WeaveGridAuthExpired):
                errors["base"] = "invalid_auth"
            except WeaveGridConnectionError:
                errors["base"] = "cannot_connect"
            except WeaveGridError:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="totp",
            data_schema=vol.Schema({vol.Required("totp_code"): str}),
            errors=errors,
        )

    async def async_step_magic_link(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Redeem the emailed WeaveGrid magic link URL or token."""
        errors: dict[str, str] = {}

        if user_input is not None and self._client is not None:
            try:
                await self._client.async_redeem_magic_link(user_input["magic_link"])
                return await self._async_finish_entry(AUTH_METHOD_MAGIC_LINK)
            except (WeaveGridInvalidAuth, WeaveGridAuthExpired):
                errors["base"] = "invalid_auth"
            except WeaveGridConnectionError:
                errors["base"] = "cannot_connect"
            except WeaveGridError:
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="magic_link",
            data_schema=vol.Schema({vol.Required("magic_link"): str}),
            description_placeholders={"email": self._email},
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle reauthentication triggered when credentials or session expire."""
        self._reauth_entry = self._get_reauth_entry()
        self._email = str(entry_data.get(CONF_EMAIL, ""))
        self._utility = str(entry_data.get(CONF_UTILITY, DEFAULT_UTILITY))
        return await self.async_step_user()


class WeaveGridOptionsFlow(OptionsFlow):
    """Handle options for WeaveGrid."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage polling interval and archived device visibility."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = int(
            self.config_entry.options.get(
                CONF_SCAN_INTERVAL,
                self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            )
        )
        current_archived = bool(
            self.config_entry.options.get(
                CONF_INCLUDE_ARCHIVED,
                self.config_entry.data.get(CONF_INCLUDE_ARCHIVED, False),
            )
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=60)
                    ),
                    vol.Required(
                        CONF_INCLUDE_ARCHIVED, default=current_archived
                    ): bool,
                }
            ),
        )
