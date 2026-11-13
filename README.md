# WeaveGrid for Home Assistant

Custom Home Assistant integration for **WeaveGrid** utility managed-charging portals (such as **BGE**, **Xcel Energy**, **PG&E**, **Pepco**, **ComEd**, **PECO**, **DTE**, **Dominion**, and others hosted on `charge.weavegrid.com`).

## Features

- **UI Setup & Automatic Re-Login**: Sign in with your WeaveGrid email & password (supports TOTP 2FA as well as passwordless Magic Link sign-in). Sessions automatically refresh in the background whenever cookies expire.
- **Per-Charger / Per-Vehicle Devices**: Automatically discovers active EVs and EVSEs (e.g., Emporia, Wallbox, ChargePoint, Tesla, Rivian, etc.), with an option to show/hide archived registrations.
- **Controls**:
  - **`Charge Now` Button**: Immediately overrides smart scheduling (`/api/settings/override`) when you need to charge right away.
  - **`Peak Avoidance` Switch**: Toggles Peak Avoidance via GraphQL while preserving your weekday/weekend ready-by times, solar hours, and low-battery protection. It only sends settings it has read back from WeaveGrid, and it is unavailable (and refuses to write) whenever the current settings couldn't be read, so your schedule is never overwritten with defaults.
- **Rich Sensors & Session History**:
  - Plugged-in, Charging, At-Home, and Smart Charging binary sensors
  - Scheduled Charge Start, Next Charge Start, and Target Ready-By timestamp sensors
  - Estimated Range Added (`mi`) and Battery Level (`%`, for direct vehicle telematics)
  - Last Session Cost, Last Session Energy (`kWh`), and Last Session Duration (`h`)
  - **Recent Charging Sessions** sensor with up to 12 recent sessions (`date`, `start`, `end`, `duration_hours`, `energy_kwh`, `cost`, `rate` (average $/kWh paid), `max_rate` (highest span price), `off_peak_energy_kwh`, `off_peak_cost`, `off_peak_percent`, `smart`, `compliant`, and per-span `spans`) in its `sessions` attribute
  - 7-Day & 30-Day Charging Cost, Charging Energy, and Smart Score (`%`)

---

## Installation

### Option A: HACS (recommended)

1. Open **HACS** in Home Assistant and search for **WeaveGrid**.
2. If it doesn't show up yet, add this repository as a custom repository: open the **⋮** menu in the upper-right corner, select **Custom repositories**, enter `https://github.com/Aryeh95/weavegrid-ha`, choose **Integration** as the type, and select **Add**.
3. Open **WeaveGrid** and select **Download**.
4. **Restart Home Assistant**.
5. Go to **Settings -> Devices & Services -> Add Integration -> WeaveGrid**.

### Option B: Manual Copy

1. Copy the `custom_components/weavegrid` directory into your Home Assistant `/config/custom_components/weavegrid` folder.
2. **Restart Home Assistant**.
3. Go to **Settings -> Devices & Services -> Add Integration -> WeaveGrid**.

---

## Entities Created (per Vehicle / EVSE)

| Platform | Entity | Description |
| :--- | :--- | :--- |
| `binary_sensor` | **Plugged In** | Whether the EV/EVSE reports plugged in |
| `binary_sensor` | **Charging** | Whether the EV/EVSE is actively charging |
| `binary_sensor` | **At Home** | Whether the vehicle/EVSE is at your home location |
| `binary_sensor` | **Smart Charging** | Active managed-charging status & TOU rate attributes |
| `button` | **Charge Now** | Triggers immediate charging override |
| `switch` | **Peak Avoidance** | Enables/disables Peak Avoidance while keeping your ready-by schedule |
| `sensor` | **Charging Status** | `Scheduled`, `Smart Charging`, `Charging (Override)`, `Plugged In (Idle)`, `Ready`, or `Unplugged` |
| `sensor` | **Scheduled Charge Start** | Planned charging start timestamp |
| `sensor` | **Next Charge Start** | Next scheduled charging segment start timestamp |
| `sensor` | **Target Ready By** | Target completion timestamp |
| `sensor` | **Estimated Range Added** | Estimated miles added by ready-by time (`mi`) |
| `sensor` | **Last Session Cost** | Cost of most recent home charging session (`USD`) |
| `sensor` | **Last Session Energy** | Energy delivered in most recent session (`kWh`) |
| `sensor` | **Last Session Duration** | Duration of most recent session (`h`) |
| `sensor` | **Recent Charging Sessions** | Date of latest session + `sessions` list attribute (last 12 sessions) |
| `sensor` | **7-Day / 30-Day Charging Cost** | Rolling 7-day and 30-day home charging cost |
| `sensor` | **7-Day / 30-Day Charging Energy** | Rolling 7-day and 30-day home energy (`kWh`) |
| `sensor` | **30-Day Smart Score** | WeaveGrid smart charging score (`%`) |

---

## Example Dashboard Cards

### 1. Recent Charging Sessions Table (Native Markdown Card)

*(Replace `emporia_pro` with your device's entity slug if different)*

```yaml
type: markdown
title: Recent EV Charging Sessions
content: |
  | Date | Energy | Duration | Rate | Cost |
  | :--- | ---: | ---: | ---: | ---: |
  {% set sessions = state_attr('sensor.emporia_pro_recent_charging_sessions', 'sessions') or [] -%}
  {% for s in sessions -%}
  | {{ s.date }} | {{ '%.1f'|format(s.energy_kwh or 0) }} kWh | {{ '%.1f'|format(s.duration_hours or 0) }} h | {{ ('$' ~ '%.3f'|format(s.rate)) if s.rate else '—' }} | **\${{ '%.2f'|format(s.cost or 0) }}** |
  {% endfor %}
```

### 2. Mushroom Smart Charging Tile + Charge Now

```yaml
type: grid
columns: 2
square: false
cards:
  - type: heading
    heading: EV Smart Charging
    icon: mdi:ev-station
  - type: custom:mushroom-template-card
    primary: Emporia Pro
    secondary: >-
      {{ states('sensor.emporia_pro_charging_status') }}
      {% if is_state('binary_sensor.emporia_pro_plugged_in', 'on') and states('sensor.emporia_pro_charge_start') not in ['unknown', 'unavailable'] %}
      · Starts {{ as_timestamp(states('sensor.emporia_pro_charge_start')) | timestamp_custom('%-I:%M %p') }}
      {% endif %}
    icon: >-
      {{ 'mdi:ev-plug-type1' if is_state('binary_sensor.emporia_pro_plugged_in', 'on') else 'mdi:power-plug-off-outline' }}
    icon_color: >-
      {{ 'green' if is_state('binary_sensor.emporia_pro_charging', 'on') else ('blue' if is_state('binary_sensor.emporia_pro_plugged_in', 'on') else 'grey') }}
    entity: sensor.emporia_pro_charging_status
  - type: tile
    entity: button.emporia_pro_charge_now
    name: Charge Now
  - type: tile
    entity: sensor.emporia_pro_last_session_cost
    name: Last Session
  - type: tile
    entity: sensor.emporia_pro_30_day_charging_cost
    name: 30-Day Cost
```
