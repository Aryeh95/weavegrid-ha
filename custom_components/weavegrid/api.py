"""Async API client for WeaveGrid."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
import re
from typing import Any
from urllib.parse import urlparse

import aiohttp
from yarl import URL

from .const import DEFAULT_BASE_URL, DEFAULT_UTILITY

_LOGGER = logging.getLogger(__name__)

GQL_LOGIN_DRIVER = """
mutation LoginDriver(
  $email: String!
  $password: String
  $method: AuthnMethod
  $answer: String
  $inviteToken: String
  $useMagicLink: Boolean
) {
  login(
    emailAddress: $email
    password: $password
    method: $method
    userInput: $answer
    inviteToken: $inviteToken
    useMagicLink: $useMagicLink
  ) {
    isLoggedIn
    user {
      userId
      utility {
        acronym
      }
    }
    status
    availableMethods
    recoveryMethods
    challenge {
      ... on SimpleCredentialChallenge {
        method
      }
    }
  }
}
"""

GQL_AUTH_USER_DATA = """
query AuthUserData($flags: [String!]!) {
  viewer {
    id
    userId
    email
    utility {
      acronym
      driverBaseUrl
      urlStr
    }
    selectedOem {
      displayName
      name
    }
    deviceIntegrationName
    hasOnlyInactiveRegistrations
    flags(keys: $flags) {
      key
      value
    }
  }
}
"""

GQL_DASHBOARD_DATA = """
query DashboardData {
  viewer {
    id
    rateScheduleCode
    ratePlan {
      rateType
    }
    registrations(includeArchivedRegistrations: true) {
      data {
        id
        registrationId
        oemId
        isActive
        isArchived
        deletedAt
        oem {
          id
          displayName
        }
      }
    }
    vehicles(includeArchivedRegistrations: true) {
      data {
        id
        vehicleId
        displayName
        registrationId
        isActive
        isDrOnly
        isEvse
        registrationIsArchived
        hasMcFeature
        hasCompletedQualifyingChargeSession
        oem {
          id
          oemId
          name
        }
        connectivityDetail {
          isActive
          isCharging
          isPluggedIn
          isHome
          deactivatedReason
        }
      }
    }
  }
}
"""

GQL_DEVICE_DATA = """
query DeviceData($vehicleId: String!) {
  viewer {
    id
    hideCostDisplay
    location {
      id
      propertyType
      timeZone
    }
    rateScheduleCode
    ratePlan {
      rateType
    }
    vehicles(vehicleId: $vehicleId, includeArchivedRegistrations: true) {
      data {
        id
        vehicleId
        displayName
        registrationId
        isActive
        isDrOnly
        isEvse
        deviceType
        registrationIsArchived
        hasMcFeature
        hideMcSettings
        hasDrFeature
        drFeatureStatus
        offPeakWindows
        currentRateType
        smartWindowRateScheduleCode
        oem {
          id
          oemId
          name
          displayName
        }
        connectivityDetail {
          isActive
          isCharging
          isPluggedIn
          isHome
          deactivatedReason
        }
      }
    }
  }
}
"""

GQL_DEVICE_STATUS_CARD = """
query DeviceStatusCard($vehicleId: String!) {
  viewer {
    id
    location {
      id
      timeZone
    }
    vehicles(
      vehicleId: $vehicleId
      includeBatteryInfo: true
      includeArchivedRegistrations: true
    ) {
      data {
        id
        vehicleId
        isEvse
        isActive
        hasMcFeature
        hideMcSettings
        displayName
        deviceStatusContentKey
        batteryStatus {
          targetSoc
          currentSoc
          lastReadDttm
        }
        mcPlanStatus {
          id
          readyByDttm
          chargeStartDttm
          stopDttm
          nextChargeStartDttm
          milesAddedByReadyByTime
          socAtReadyByTime
        }
      }
    }
  }
}
"""

GQL_VEHICLE_MOST_RECENT_PLAN = """
query VehicleMostRecentPlan($vehicleId: String!) {
  viewer {
    id
    vehicles(vehicleId: $vehicleId) {
      data {
        id
        vehicleId
        plans(limit: 1, sort: PLAN_ID_DESC) {
          data {
            id
            planId
            startDttm
            finishedDttm
          }
        }
      }
    }
  }
}
"""

GQL_VEHICLE_PLAN_DETAILS = """
query VehiclePlanDetails($vehicleId: String!, $planId: Int!) {
  viewer {
    id
    vehicles(vehicleId: $vehicleId) {
      data {
        id
        vehicleId
        mcPlanStatus {
          planOutcome
          planFeatures
        }
        plans(planId: $planId) {
          data {
            id
            planId
            startDttm
            finishedDttm
            offPeakEnergyPercent
          }
        }
      }
    }
  }
}
"""

GQL_MANAGED_CHARGE_SETTINGS = """
query ManagedChargeSettings($vehicleId: String!) {
  viewer {
    id
    vehicles(vehicleId: $vehicleId, includeBatteryInfo: true) {
      data {
        id
        chargeScheduledSmsPreview
        mcSettings {
          chargeByTimes {
            Mon
            Tue
            Wed
            Thu
            Fri
            Sat
            Sun
          }
          enablePeakAvoidance
          enableLowSocProtection
          solarHours {
            startTimeLocal
            endTimeLocal
          }
        }
      }
    }
  }
}
"""

GQL_CHARGE_EVENT_AGGREGATES = """
query ChargeEventAggregates(
  $vehicleId: String!
  $startDttm: DateTime!
  $endDttm: DateTime!
  $limit: Int
) {
  viewer {
    userId
    vehicles(vehicleId: $vehicleId, includeArchivedRegistrations: true) {
      data {
        id
        vehicleId
        chargeEvents(
          inclusiveStartDttm: $startDttm
          inclusiveEndDttm: $endDttm
          locationRelationshipTypes: [home_primary]
          limit: $limit
        ) {
          totalAggregates: aggregates(
            aggregateUnit: total
            exclusiveStartDttm: $startDttm
            exclusiveEndDttm: $endDttm
          ) {
            data {
              usageDate
              chargeCost
              offPeakChargingCost
              offPeakEnergyDeliveredKwh
              totalSmartChargingCost
              chargeCostUnit
              energyDeliveredKwh
              smartScore
              smartScoreType
            }
          }
          dailyAggregates: aggregates(
            aggregateUnit: day
            exclusiveStartDttm: $startDttm
            exclusiveEndDttm: $endDttm
            limit: $limit
          ) {
            data {
              usageDate
              chargeCost
              offPeakChargingCost
              offPeakEnergyDeliveredKwh
              totalSmartChargingCost
              chargeCostUnit
              energyDeliveredKwh
              smartScore
              smartScoreType
            }
          }
        }
      }
    }
  }
}
"""

GQL_HOME_CHARGE_HISTORY = """
query userVehiclesHomeChargeHistory(
  $vehicleId: String
  $chargeEventsLimit: Int
  $locationRelationshipTypes: [RelationshipTypeEnum]
  $includeArchivedRegistrations: Boolean
) {
  viewer {
    id
    hideCostDisplay
    vehicles(
      vehicleId: $vehicleId
      includeArchivedRegistrations: $includeArchivedRegistrations
    ) {
      data {
        vehicleId
        displayName
        chargeEvents(
          first: $chargeEventsLimit
          locationRelationshipTypes: $locationRelationshipTypes
        ) {
          userTimeZone
          aggregates(aggregateUnit: day) {
            data {
              aggregateUnit
              startDttm
              endDttm
              usageDate
              userTimeZone
              chargeHours
              energyDeliveredKwh
              chargeCost
              chargeCostUnit
            }
          }
          chargeSpans {
            data {
              startDttm
              endDttm
              usageDate
              electricityRate
              electricityRateUnit
              smartScoreType
              isSmart
              isManageable
              isMcCompliant
              locationRelationshipType
            }
          }
        }
      }
    }
  }
}
"""

GQL_UPDATE_MC_SETTINGS = """
mutation UpdateMcSettings(
  $vehicleId: ID!
  $chargeByTimes: ChargeByTimesMutationInput
  $enableLowSocProtection: Boolean
  $enablePeakAvoidance: Boolean
  $solarHours: SolarHoursMutationInput
) {
  updateMcSettings(
    vehicleId: $vehicleId
    chargeByTimes: $chargeByTimes
    enableLowSocProtection: $enableLowSocProtection
    enablePeakAvoidance: $enablePeakAvoidance
    solarHours: $solarHours
  ) {
    vehicle {
      id
      chargeScheduledSmsPreview
      mcSettings {
        chargeByTimes {
          Mon
          Tue
          Wed
          Thu
          Fri
          Sat
          Sun
        }
        enablePeakAvoidance
        enableLowSocProtection
        solarHours {
          startTimeLocal
          endTimeLocal
        }
      }
    }
  }
}
"""


class WeaveGridError(Exception):
    """Base exception for WeaveGrid API errors."""


class WeaveGridConnectionError(WeaveGridError):
    """Raised on network or HTTP failures."""


class WeaveGridInvalidAuth(WeaveGridError):
    """Raised when login credentials or session cookie are rejected."""


class WeaveGridAuthExpired(WeaveGridError):
    """Raised when the active session cookie expires."""


class WeaveGridTwoFactorRequired(WeaveGridError):
    """Raised when login succeeds primary step and requires TOTP 2FA."""

    def __init__(self, challenge_method: str = "totp") -> None:
        super().__init__(f"Two-factor authentication required ({challenge_method})")
        self.challenge_method = challenge_method


@dataclass
class ChargeSessionSummary:
    """Normalized record of a single home charging day/session."""

    usage_date: str | None
    start_dttm: str | None
    end_dttm: str | None
    charge_hours: float | None
    energy_kwh: float | None
    charge_cost: float | None
    cost_unit: str
    electricity_rate: float | None = None
    is_smart: bool | None = None
    is_mc_compliant: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize session summary for Home Assistant state attributes."""
        return {
            "date": self.usage_date,
            "start": self.start_dttm,
            "end": self.end_dttm,
            "duration_hours": round(self.charge_hours, 2)
            if self.charge_hours is not None
            else None,
            "energy_kwh": round(self.energy_kwh, 2)
            if self.energy_kwh is not None
            else None,
            "cost": round(self.charge_cost, 2)
            if self.charge_cost is not None
            else None,
            "currency": self.cost_unit,
            "rate": self.electricity_rate,
            "smart": self.is_smart,
            "compliant": self.is_mc_compliant,
        }


@dataclass
class WeaveGridVehicleData:
    """Normalized snapshot of a single EV or EVSE registered with WeaveGrid."""

    vehicle_id: str
    display_name: str
    oem_name: str
    is_active: bool
    is_archived: bool
    is_evse: bool
    has_mc_feature: bool
    hide_mc_settings: bool

    # Connectivity
    is_plugged_in: bool | None = None
    is_charging: bool | None = None
    is_home: bool | None = None
    deactivated_reason: str | None = None

    # Rate / DR
    rate_schedule_code: str | None = None
    current_rate_type: str | None = None
    dr_feature_status: str | None = None
    off_peak_windows: Any = None
    time_zone: str | None = None

    # Status card & schedule
    status_key: str | None = None
    charge_start_dttm: str | None = None
    next_charge_start_dttm: str | None = None
    ready_by_dttm: str | None = None
    stop_dttm: str | None = None
    miles_added_by_ready_time: float | None = None
    soc_at_ready_time: float | None = None

    # Battery (for direct vehicle telematics integrations)
    current_soc: float | None = None
    target_soc: float | None = None
    battery_last_read_dttm: str | None = None

    # Most recent plan details
    plan_id: int | None = None
    plan_start_dttm: str | None = None
    plan_finished_dttm: str | None = None
    plan_outcome: str | None = None
    off_peak_energy_percent: float | None = None

    # Managed charge preferences
    mc_settings: dict[str, Any] = field(default_factory=dict)
    sms_preview: str | None = None

    # 7-day & 30-day aggregates
    cost_7d: float = 0.0
    energy_7d_kwh: float = 0.0
    cost_30d: float = 0.0
    off_peak_cost_30d: float = 0.0
    smart_cost_30d: float = 0.0
    energy_30d_kwh: float = 0.0
    off_peak_energy_30d_kwh: float = 0.0
    cost_unit: str = "USD"
    smart_score_30d: float | None = None
    smart_score_type: str | None = None

    # Recent charging sessions (newest first)
    recent_sessions: list[ChargeSessionSummary] = field(default_factory=list)


@dataclass
class WeaveGridAccountData:
    """Account-wide snapshot returned by the coordinator."""

    user_id: str
    email: str | None
    utility_acronym: str
    rate_schedule_code: str | None
    rate_type: str | None
    vehicles: dict[str, WeaveGridVehicleData] = field(default_factory=dict)


class WeaveGridApiClient:
    """Async client for WeaveGrid's GraphQL and REST driver portal endpoints."""

    def __init__(
        self,
        utility_acronym: str = DEFAULT_UTILITY,
        base_url: str = DEFAULT_BASE_URL,
        session_cookie: str | None = None,
    ) -> None:
        self.utility_acronym = (utility_acronym or DEFAULT_UTILITY).strip().lower()
        self.base_url = base_url.rstrip("/")
        self._cookie_jar = aiohttp.CookieJar()
        self._session: aiohttp.ClientSession | None = None
        if session_cookie:
            self.set_session_cookie(session_cookie)

    def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(
                cookie_jar=self._cookie_jar,
                timeout=timeout,
            )
        return self._session

    async def async_close(self) -> None:
        """Close the isolated HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    def set_session_cookie(self, cookie_value: str) -> None:
        """Seed the isolated cookie jar with a WeaveGrid session cookie."""
        val = cookie_value.strip()
        if val.startswith("session="):
            val = val.split("session=", 1)[1].split(";", 1)[0].strip()
        self._cookie_jar.update_cookies({"session": val}, URL(self.base_url))

    def get_session_cookie(self) -> str | None:
        """Extract the current session cookie value for persistence."""
        cookies = self._cookie_jar.filter_cookies(URL(self.base_url))
        morsel = cookies.get("session")
        return morsel.value if morsel else None

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/{self.utility_acronym}/dashboard/",
            "User-Agent": "HomeAssistant-WeaveGrid/0.1.0",
            "X-WG-Utility-Acronym": self.utility_acronym,
        }

    async def _async_graphql_batch(
        self, operations: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Execute GraphQL POST request(s) against /graphql (max 5 per batch)."""
        max_batch_size = 5
        if len(operations) > max_batch_size:
            combined: list[dict[str, Any]] = []
            for idx in range(0, len(operations), max_batch_size):
                chunk = operations[idx : idx + max_batch_size]
                combined.extend(await self._async_graphql_batch(chunk))
            return combined

        session = self._ensure_session()
        url = f"{self.base_url}/graphql"
        try:
            async with session.post(
                url, json=operations, headers=self._headers()
            ) as resp:
                if resp.status in (401, 403):
                    raise WeaveGridAuthExpired(f"HTTP {resp.status} from GraphQL")
                if resp.status >= 400:
                    body = await resp.text()
                    raise WeaveGridConnectionError(
                        f"GraphQL HTTP {resp.status}: {body[:200]}"
                    )
                payload = await resp.json()
        except aiohttp.ClientError as err:
            raise WeaveGridConnectionError(f"Network error: {err}") from err

        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list):
            return payload
        raise WeaveGridError("Unexpected GraphQL response type")

    async def async_login(self, email: str, password: str) -> dict[str, Any]:
        """Authenticate via email and password using LoginDriver."""
        results = await self._async_graphql_batch(
            [
                {
                    "operationName": "LoginDriver",
                    "variables": {
                        "email": email.strip(),
                        "password": password,
                        "useMagicLink": False,
                    },
                    "query": GQL_LOGIN_DRIVER,
                }
            ]
        )
        res = results[0]
        if res.get("errors") and not res.get("data"):
            msg = res["errors"][0].get("message", "Login failed")
            raise WeaveGridInvalidAuth(msg)

        login_data = (res.get("data") or {}).get("login") or {}
        status = (login_data.get("status") or "").lower()
        is_logged_in = bool(login_data.get("isLoggedIn"))

        if status == "primary_accepted_challenge_required":
            challenge = login_data.get("challenge") or {}
            raise WeaveGridTwoFactorRequired(challenge.get("method") or "totp")

        if not is_logged_in and status != "authenticated":
            raise WeaveGridInvalidAuth(
                f"Login unsuccessful (status={login_data.get('status')})"
            )

        user_info = login_data.get("user") or {}
        util_info = user_info.get("utility") or {}
        if util_info.get("acronym"):
            self.utility_acronym = util_info["acronym"].strip().lower()

        return login_data

    async def async_verify_totp(self, email: str, totp_code: str) -> dict[str, Any]:
        """Complete TOTP second-factor challenge."""
        clean_code = re.sub(r"[^0-9]", "", totp_code)
        results = await self._async_graphql_batch(
            [
                {
                    "operationName": "LoginDriver",
                    "variables": {
                        "email": email.strip(),
                        "method": "totp",
                        "answer": clean_code,
                    },
                    "query": GQL_LOGIN_DRIVER,
                }
            ]
        )
        login_data = (results[0].get("data") or {}).get("login") or {}
        status = (login_data.get("status") or "").lower()
        if not login_data.get("isLoggedIn") and status != "authenticated":
            raise WeaveGridInvalidAuth("Invalid verification code")

        user_info = login_data.get("user") or {}
        util_info = user_info.get("utility") or {}
        if util_info.get("acronym"):
            self.utility_acronym = util_info["acronym"].strip().lower()
        return login_data

    async def async_request_magic_link(self, email: str) -> None:
        """Trigger a sign-in magic link email from WeaveGrid."""
        await self._async_graphql_batch(
            [
                {
                    "operationName": "LoginDriver",
                    "variables": {
                        "email": email.strip(),
                        "useMagicLink": True,
                    },
                    "query": GQL_LOGIN_DRIVER,
                }
            ]
        )

    async def async_redeem_magic_link(self, token_or_url: str) -> None:
        """Redeem a magic link URL or token to establish a session cookie."""
        token = self._extract_magic_token(token_or_url)
        session = self._ensure_session()
        url = f"{self.base_url}/api/auth/magic-link-auth/{token}?source=login"
        try:
            async with session.post(url, headers=self._headers()) as resp:
                if resp.status >= 400:
                    raise WeaveGridInvalidAuth(
                        f"Magic link redemption failed (HTTP {resp.status})"
                    )
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise WeaveGridConnectionError(f"Network error: {err}") from err

        if data.get("error_msg"):
            raise WeaveGridInvalidAuth(str(data["error_msg"]))

    @staticmethod
    def _extract_magic_token(token_or_url: str) -> str:
        raw = token_or_url.strip()
        if "://" in raw:
            parsed = urlparse(raw)
            parts = [p for p in parsed.path.split("/") if p]
            if parts:
                return parts[-1]
        return raw

    async def async_validate_session(self) -> dict[str, Any]:
        """Verify current session cookie and return AuthUserData viewer dict."""
        results = await self._async_graphql_batch(
            [
                {
                    "operationName": "AuthUserData",
                    "variables": {
                        "flags": [
                            "public-show-charge-plan-diagram",
                            "driver-ui-show-solar-mcsettings",
                        ]
                    },
                    "query": GQL_AUTH_USER_DATA,
                }
            ]
        )
        viewer = (results[0].get("data") or {}).get("viewer")
        if not viewer or not viewer.get("userId"):
            raise WeaveGridAuthExpired("Session is not authenticated")

        util_info = viewer.get("utility") or {}
        if util_info.get("acronym"):
            self.utility_acronym = util_info["acronym"].strip().lower()
        return viewer

    async def async_fetch_all(
        self, include_archived: bool = False
    ) -> WeaveGridAccountData:
        """Fetch account data and per-device details, schedules, and session history."""
        top_results = await self._async_graphql_batch(
            [
                {
                    "operationName": "AuthUserData",
                    "variables": {
                        "flags": [
                            "public-show-charge-plan-diagram",
                            "driver-ui-show-solar-mcsettings",
                        ]
                    },
                    "query": GQL_AUTH_USER_DATA,
                },
                {
                    "operationName": "DashboardData",
                    "variables": {},
                    "query": GQL_DASHBOARD_DATA,
                },
            ]
        )

        auth_viewer = (top_results[0].get("data") or {}).get("viewer")
        dash_viewer = (top_results[1].get("data") or {}).get("viewer")
        if not auth_viewer or not dash_viewer:
            raise WeaveGridAuthExpired("WeaveGrid session expired (viewer is null)")

        util_info = auth_viewer.get("utility") or {}
        if util_info.get("acronym"):
            self.utility_acronym = util_info["acronym"].strip().lower()

        # Map registrationId -> OEM displayName
        reg_oem_names: dict[str, str] = {}
        for reg in ((dash_viewer.get("registrations") or {}).get("data")) or []:
            reg_id = str(reg.get("registrationId") or "")
            oem_disp = ((reg.get("oem") or {}).get("displayName")) or ""
            if reg_id and oem_disp:
                reg_oem_names[reg_id] = oem_disp

        account = WeaveGridAccountData(
            user_id=str(auth_viewer.get("userId") or ""),
            email=auth_viewer.get("email"),
            utility_acronym=self.utility_acronym,
            rate_schedule_code=dash_viewer.get("rateScheduleCode"),
            rate_type=(dash_viewer.get("ratePlan") or {}).get("rateType"),
        )

        raw_vehicles = ((dash_viewer.get("vehicles") or {}).get("data")) or []
        now_utc = datetime.now(timezone.utc)
        start_30d = (now_utc - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        end_30d = (now_utc + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        cutoff_7d_date = (now_utc - timedelta(days=7)).date().isoformat()

        for raw_v in raw_vehicles:
            is_archived = bool(raw_v.get("registrationIsArchived"))
            is_active = bool(raw_v.get("isActive"))
            if not include_archived and (is_archived or not is_active):
                continue

            vid = str(raw_v.get("vehicleId"))
            reg_id = str(raw_v.get("registrationId") or "")
            oem_obj = raw_v.get("oem") or {}
            oem_name = (
                reg_oem_names.get(reg_id)
                or oem_obj.get("displayName")
                or (oem_obj.get("name") or "WeaveGrid").title()
            )

            v_batch = await self._async_graphql_batch(
                [
                    {
                        "operationName": "DeviceData",
                        "variables": {"vehicleId": vid},
                        "query": GQL_DEVICE_DATA,
                    },
                    {
                        "operationName": "DeviceStatusCard",
                        "variables": {"vehicleId": vid},
                        "query": GQL_DEVICE_STATUS_CARD,
                    },
                    {
                        "operationName": "VehicleMostRecentPlan",
                        "variables": {"vehicleId": vid},
                        "query": GQL_VEHICLE_MOST_RECENT_PLAN,
                    },
                    {
                        "operationName": "ManagedChargeSettings",
                        "variables": {"vehicleId": vid},
                        "query": GQL_MANAGED_CHARGE_SETTINGS,
                    },
                    {
                        "operationName": "ChargeEventAggregates",
                        "variables": {
                            "vehicleId": vid,
                            "startDttm": start_30d,
                            "endDttm": end_30d,
                            "limit": 1000,
                        },
                        "query": GQL_CHARGE_EVENT_AGGREGATES,
                    },
                    {
                        "operationName": "userVehiclesHomeChargeHistory",
                        "variables": {
                            "vehicleId": vid,
                            "chargeEventsLimit": 10,
                            "locationRelationshipTypes": ["home_primary"],
                            "includeArchivedRegistrations": True,
                        },
                        "query": GQL_HOME_CHARGE_HISTORY,
                    },
                ]
            )

            dev_viewer = (v_batch[0].get("data") or {}).get("viewer") or {}
            dev_v = self._first_vehicle(dev_viewer)
            card_viewer = (v_batch[1].get("data") or {}).get("viewer") or {}
            card_v = self._first_vehicle(card_viewer)
            plan_v = self._first_vehicle(
                (v_batch[2].get("data") or {}).get("viewer") or {}
            )
            mc_v = self._first_vehicle(
                (v_batch[3].get("data") or {}).get("viewer") or {}
            )
            agg_v = self._first_vehicle(
                (v_batch[4].get("data") or {}).get("viewer") or {}
            )
            hist_v = self._first_vehicle(
                (v_batch[5].get("data") or {}).get("viewer") or {}
            )

            conn = (dev_v.get("connectivityDetail") or raw_v.get("connectivityDetail")) or {}
            mc_plan = card_v.get("mcPlanStatus") or {}
            batt = card_v.get("batteryStatus") or {}
            loc = card_viewer.get("location") or dev_viewer.get("location") or {}

            dev_oem = (dev_v.get("oem") or {}).get("displayName")
            if dev_oem:
                oem_name = dev_oem

            recent_plans = ((plan_v.get("plans") or {}).get("data")) or []
            latest_plan = recent_plans[0] if recent_plans else {}
            plan_id = latest_plan.get("planId")

            plan_outcome: str | None = None
            off_peak_pct: float | None = None
            if plan_id is not None:
                try:
                    p_res = await self._async_graphql_batch(
                        [
                            {
                                "operationName": "VehiclePlanDetails",
                                "variables": {
                                    "vehicleId": vid,
                                    "planId": int(plan_id),
                                },
                                "query": GQL_VEHICLE_PLAN_DETAILS,
                            }
                        ]
                    )
                    pv = self._first_vehicle(
                        (p_res[0].get("data") or {}).get("viewer") or {}
                    )
                    plan_outcome = (pv.get("mcPlanStatus") or {}).get("planOutcome")
                    p_items = ((pv.get("plans") or {}).get("data")) or []
                    if p_items:
                        off_peak_pct = p_items[0].get("offPeakEnergyPercent")
                except WeaveGridError as err:
                    _LOGGER.debug("Could not fetch VehiclePlanDetails for %s: %s", vid, err)

            vehicle_data = WeaveGridVehicleData(
                vehicle_id=vid,
                display_name=dev_v.get("displayName")
                or raw_v.get("displayName")
                or f"WeaveGrid {vid}",
                oem_name=oem_name,
                is_active=is_active,
                is_archived=is_archived,
                is_evse=bool(dev_v.get("isEvse", raw_v.get("isEvse", False))),
                has_mc_feature=bool(
                    dev_v.get("hasMcFeature", raw_v.get("hasMcFeature", False))
                ),
                hide_mc_settings=bool(dev_v.get("hideMcSettings", False)),
                is_plugged_in=conn.get("isPluggedIn"),
                is_charging=conn.get("isCharging"),
                is_home=conn.get("isHome"),
                deactivated_reason=conn.get("deactivatedReason"),
                rate_schedule_code=dev_viewer.get("rateScheduleCode")
                or account.rate_schedule_code,
                current_rate_type=dev_v.get("currentRateType") or account.rate_type,
                dr_feature_status=dev_v.get("drFeatureStatus"),
                off_peak_windows=dev_v.get("offPeakWindows"),
                time_zone=loc.get("timeZone"),
                status_key=card_v.get("deviceStatusContentKey"),
                charge_start_dttm=mc_plan.get("chargeStartDttm"),
                next_charge_start_dttm=mc_plan.get("nextChargeStartDttm"),
                ready_by_dttm=mc_plan.get("readyByDttm"),
                stop_dttm=mc_plan.get("stopDttm"),
                miles_added_by_ready_time=mc_plan.get("milesAddedByReadyByTime"),
                soc_at_ready_time=mc_plan.get("socAtReadyByTime"),
                current_soc=batt.get("currentSoc"),
                target_soc=batt.get("targetSoc"),
                battery_last_read_dttm=batt.get("lastReadDttm"),
                plan_id=int(plan_id) if plan_id is not None else None,
                plan_start_dttm=latest_plan.get("startDttm"),
                plan_finished_dttm=latest_plan.get("finishedDttm"),
                plan_outcome=plan_outcome,
                off_peak_energy_percent=off_peak_pct,
                mc_settings=mc_v.get("mcSettings") or {},
                sms_preview=mc_v.get("chargeScheduledSmsPreview"),
            )

            self._populate_aggregates(vehicle_data, agg_v, cutoff_7d_date)
            self._populate_history(vehicle_data, hist_v)

            account.vehicles[vid] = vehicle_data

        return account

    @staticmethod
    def _first_vehicle(viewer: dict[str, Any]) -> dict[str, Any]:
        items = ((viewer.get("vehicles") or {}).get("data")) or []
        return items[0] if items else {}

    @staticmethod
    def _populate_aggregates(
        target: WeaveGridVehicleData, agg_v: dict[str, Any], cutoff_7d_date: str
    ) -> None:
        ce = agg_v.get("chargeEvents") or {}
        totals = ((ce.get("totalAggregates") or {}).get("data")) or []
        if totals:
            t0 = totals[0]
            target.cost_30d = float(t0.get("chargeCost") or 0.0)
            target.off_peak_cost_30d = float(t0.get("offPeakChargingCost") or 0.0)
            target.smart_cost_30d = float(t0.get("totalSmartChargingCost") or 0.0)
            target.energy_30d_kwh = float(t0.get("energyDeliveredKwh") or 0.0)
            target.off_peak_energy_30d_kwh = float(
                t0.get("offPeakEnergyDeliveredKwh") or 0.0
            )
            target.cost_unit = t0.get("chargeCostUnit") or "USD"
            if t0.get("smartScore") is not None:
                target.smart_score_30d = float(t0["smartScore"])
            target.smart_score_type = t0.get("smartScoreType")

        dailies = ((ce.get("dailyAggregates") or {}).get("data")) or []
        cost_7d = 0.0
        energy_7d = 0.0
        for row in dailies:
            u_date = str(row.get("usageDate") or "")
            if u_date >= cutoff_7d_date:
                cost_7d += float(row.get("chargeCost") or 0.0)
                energy_7d += float(row.get("energyDeliveredKwh") or 0.0)
        target.cost_7d = cost_7d
        target.energy_7d_kwh = energy_7d

    @staticmethod
    def _populate_history(
        target: WeaveGridVehicleData, hist_v: dict[str, Any]
    ) -> None:
        ce = hist_v.get("chargeEvents") or {}
        agg_rows = ((ce.get("aggregates") or {}).get("data")) or []
        span_rows = ((ce.get("chargeSpans") or {}).get("data")) or []

        # Index spans by usageDate for rate & compliance enrichment
        spans_by_date: dict[str, list[dict[str, Any]]] = {}
        for sp in span_rows:
            d_key = str(sp.get("usageDate") or "")
            if d_key:
                spans_by_date.setdefault(d_key, []).append(sp)

        sessions: list[ChargeSessionSummary] = []
        sorted_aggs = sorted(
            agg_rows,
            key=lambda r: str(r.get("startDttm") or r.get("usageDate") or ""),
            reverse=True,
        )
        for row in sorted_aggs:
            u_date = row.get("usageDate")
            day_spans = spans_by_date.get(str(u_date or ""), [])
            rate = day_spans[0].get("electricityRate") if day_spans else None
            is_smart = (
                all(bool(s.get("isSmart")) for s in day_spans)
                if day_spans
                else None
            )
            is_compliant = (
                all(bool(s.get("isMcCompliant")) for s in day_spans)
                if day_spans
                else None
            )
            sessions.append(
                ChargeSessionSummary(
                    usage_date=u_date,
                    start_dttm=row.get("startDttm"),
                    end_dttm=row.get("endDttm"),
                    charge_hours=float(row["chargeHours"])
                    if row.get("chargeHours") is not None
                    else None,
                    energy_kwh=float(row["energyDeliveredKwh"])
                    if row.get("energyDeliveredKwh") is not None
                    else None,
                    charge_cost=float(row["chargeCost"])
                    if row.get("chargeCost") is not None
                    else None,
                    cost_unit=row.get("chargeCostUnit") or target.cost_unit or "USD",
                    electricity_rate=float(rate) if rate is not None else None,
                    is_smart=is_smart,
                    is_mc_compliant=is_compliant,
                )
            )

        target.recent_sessions = sessions

    async def async_charge_now(self, vehicle_id: str) -> dict[str, Any]:
        """Trigger immediate charging override ('Charge now') for a vehicle/EVSE."""
        session = self._ensure_session()
        url = f"{self.base_url}/api/settings/override"
        body = {"vehicle_id": int(vehicle_id)}
        try:
            async with session.post(
                url, json=body, headers=self._headers()
            ) as resp:
                if resp.status in (401, 403):
                    raise WeaveGridAuthExpired("Session expired calling override")
                if resp.status >= 400:
                    text = await resp.text()
                    raise WeaveGridError(
                        f"Charge Now override failed (HTTP {resp.status}): {text[:200]}"
                    )
                data = await resp.json()
        except aiohttp.ClientError as err:
            raise WeaveGridConnectionError(f"Network error: {err}") from err

        if isinstance(data, dict) and data.get("status") == -1:
            raise WeaveGridError(f"WeaveGrid rejected Charge Now override: {data}")
        return data if isinstance(data, dict) else {"status": "ok"}

    async def async_set_peak_avoidance(
        self,
        vehicle_id: str,
        enabled: bool,
        current_mc_settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Enable or disable Peak Avoidance while preserving existing schedule settings."""
        mc = current_mc_settings or {}
        raw_times = mc.get("chargeByTimes") or {}
        days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
        charge_by_times = {
            day: raw_times.get(day) or "07:00" for day in days
        }
        raw_solar = mc.get("solarHours") or {}
        solar_hours: dict[str, Any] = {}
        if raw_solar.get("startTimeLocal") and raw_solar.get("endTimeLocal"):
            solar_hours = {
                "startTimeLocal": raw_solar["startTimeLocal"],
                "endTimeLocal": raw_solar["endTimeLocal"],
            }

        variables: dict[str, Any] = {
            "vehicleId": str(vehicle_id),
            "chargeByTimes": charge_by_times,
            "enablePeakAvoidance": bool(enabled),
            "enableLowSocProtection": mc.get("enableLowSocProtection"),
            "solarHours": solar_hours,
        }
        results = await self._async_graphql_batch(
            [
                {
                    "operationName": "UpdateMcSettings",
                    "variables": variables,
                    "query": GQL_UPDATE_MC_SETTINGS,
                }
            ]
        )
        res = results[0]
        if res.get("errors"):
            raise WeaveGridError(
                f"UpdateMcSettings failed: {res['errors'][0].get('message')}"
            )
        return (
            ((res.get("data") or {}).get("updateMcSettings") or {})
            .get("vehicle", {})
            .get("mcSettings")
            or {}
        )
