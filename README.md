# Heat Manager

**Intelligent heating control for Home Assistant.**

Heat Manager replaces manual YAML automations with a fully configurable
custom integration. It manages presence-based heating, open window detection,
pre-heating on arrival, seasonal on/off control, and mold risk monitoring —
all from the UI.

[![Version](https://img.shields.io/badge/version-0.3.9-blue)](https://github.com/kingpainter/heat-manager/releases)
[![HA min version](https://img.shields.io/badge/Home%20Assistant-%3E%3D2025.1-blue)](https://www.home-assistant.io)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange)](https://hacs.xyz)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What it does

Heat Manager watches who is home and what windows are open, then makes
intelligent decisions about your heating — so you don't have to think about it.

When everyone leaves, it waits a configurable grace period then sets all
climate entities to an away temperature (adaptive based on outdoor weather).
When someone arrives, it checks windows are closed before resuming the schedule.
If a window is open in a specific room, only that room's heating drops — not
the whole house.

The integration has a top-level **On / Pause / Off** controller. Pause
freezes all logic temporarily (with a timer) while preserving room states.
Off shuts everything down permanently — with the correct fallback per season.

---

## Features

- **Presence engine** — grace periods configurable per time of day (day/night)
- **Window detection** — per-room state machine, CO₂-aware notifications ("ventilation" vs "heat loss")
- **Season engine** — AUTO mode detects Winter/Summer from outdoor temperature history
- **Adaptive away temperature** — warmer setpoint on mild days, cooler on cold days
- **Local outdoor temperature sensor** — optional dedicated sensor overrides weather entity
- **ON / PAUSE / OFF controller** — manual and automatic (season + outdoor temp)
- **Pre-heat engine** — starts heating before arrival using `sensor.<person>_travel_time_home`, per-person lead time up to 90 min
- **PID controller** — discrete-time PI controller sends proportional setpoints every 60 s
- **External room temperature sensor** — optional per-room probe for PID feedback
- **Netatmo HomeKit local path** — PID writes directly to Netatmo Relay via HAP on LAN (<100 ms)
- **Zigbee TRV support** — full TRV-type routing (Netatmo vs Z2M) throughout all engines
- **Energy waste tracking** — `heating_power_request` × room wattage, CO₂-weighted
- **Energy savings tracking** — estimated kWh saved from away mode
- **Efficiency score** — daily 0–100 score
- **Valve protection** — weekly valve exercise during a night window to prevent calcification when heating is off
- **Mold risk sensor** — per-room binary sensor based on DIN 4108-2 (Magnus formula dewpoint vs humidity)
- **Cloud status banner** — panel detects Netatmo cloud outages via entity state and staleness
- **Sidebar panel** — Indeklima design language: SVG controller ring, room state grid, efficiency ring
- **Lovelace card** — matching design: amber heat palette, SVG ring, room state chips
- **Diagnostics** — downloadable snapshot from Settings → Heat Manager → ⋮ → Download diagnostics
- **Full English + Danish translations**

---

## Requirements

- Home Assistant 2025.1 or newer
- At least one `climate.*` entity per room
- `person.*` entities for presence tracking
- `binary_sensor.*` entities for window/door sensors (optional but recommended)
- `weather.*` entity for adaptive temperature and season auto-detection (optional)

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant.
2. Go to **Integrations** → three-dot menu → **Custom repositories**.
3. Add: `https://github.com/kingpainter/heat-manager` — Category: **Integration**.
4. Search for "Heat Manager" and click **Download**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration** → search "Heat Manager".

### Manual

1. Download the latest release from [GitHub Releases](https://github.com/kingpainter/heat-manager/releases).
2. Copy the `custom_components/heat_manager` folder to your HA config directory.
3. Restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** → search "Heat Manager".

---

## Configuration

Heat Manager is configured entirely through the UI. After adding the integration,
a 4-step wizard guides you through setup.

### Step 1 — Season & global settings

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `weather_entity` | entity | — | Weather entity for outdoor temperature and season detection |
| `outdoor_temp_sensor` | entity | — | **Optional.** Local outdoor sensor (e.g. Netatmo outdoor module, Aqara). Overrides weather entity temperature |
| `notify_service` | string | — | HA notify service, e.g. `notify.mobile_app_my_phone` |
| `away_temp_mild` | °C | 17.0 | Away setpoint when outdoor temp is above the mild threshold |
| `away_temp_cold` | °C | 15.0 | Away setpoint when outdoor temp is below the mild threshold |
| `mild_threshold` | °C | 8.0 | Boundary between "mild" and "cold" weather |
| `grace_day_min` | min | 30 | Grace period before away mode (daytime) |
| `grace_night_min` | min | 15 | Grace period before away mode (night, 23:00–07:00) |
| `auto_off_temp_threshold` | °C | 18.0 | Outdoor temperature above which auto-off fires |
| `auto_off_temp_days` | days | 5 | Consecutive days above threshold before auto-off |

### Step 2 — Rooms (repeatable)

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `room_name` | string | — | Display name (e.g. "Kitchen") |
| `climate_entity` | entity | — | Primary climate entity |
| `homekit_climate_entity` | entity | — | **Optional.** HomeKit local entity for PID writes (Netatmo Relay via HAP) |
| `window_sensors` | entity list | [] | Window/door sensors for this room |
| `window_delay_min` | min | 5 | Minutes open before heating drops |
| `away_temp_override` | °C | 10.0 | Frost-guard floor when window opens |
| `room_wattage` | W | 1000 | Rated heating power for energy calculations |
| `trv_type` | select | netatmo | `netatmo` (preset_mode) or `zigbee` (hvac_mode) |
| `pi_demand_entity` | entity | — | **Optional.** Z2M `pi_heating_demand` sensor entity |
| `co2_sensor` | entity | — | **Optional.** CO₂ sensor — context-aware window notifications and waste weighting |
| `room_temp_sensor` | entity | — | **Optional.** Independent temperature probe for PID feedback |
| `humidity_sensor` | entity | — | **Optional.** Humidity sensor for mold risk detection |

### Step 3 — Persons (repeatable)

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `person_entity` | entity | — | The `person.*` entity |
| `person_tracking` | bool | true | Enable presence tracking |
| `preheat_lead_time_min` | min | 20 | Minutes before ETA to start pre-heating (per person, max 90 min) |

### Step 4 — Notifications

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `notify_presence` | bool | true | Notify on presence-based heating changes |
| `notify_windows` | bool | true | Notify when a window drops heating |
| `notify_window_warning_30` | bool | true | Warning if window open 30+ minutes |
| `notify_preheat` | bool | true | Notify when pre-heat starts |
| `energy_tracking` | bool | true | Enable energy waste sensor |

---

## Services

### `heat_manager.set_controller_state`

```yaml
action: heat_manager.set_controller_state
data:
  state: "off"
```

### `heat_manager.pause`

```yaml
action: heat_manager.pause
data:
  duration_minutes: 60
```

### `heat_manager.resume`

```yaml
action: heat_manager.resume
```

### `heat_manager.force_room_on`

```yaml
action: heat_manager.force_room_on
data:
  room_name: "Kitchen"
```

---

## Entities

| Entity | Type | Default | Description |
|--------|------|---------|-------------|
| `select.heat_manager_controller_state` | Select | **on** | On / Pause / Off — main control |
| `select.heat_manager_season_mode` | Select | disabled | Auto / Winter / Summer |
| `sensor.heat_manager_pause_remaining` | Sensor | disabled | Minutes left in pause (DIAGNOSTIC) |
| `sensor.heat_manager_energy_wasted_today` | Sensor | **on** | kWh wasted today (CO₂-weighted) |
| `sensor.heat_manager_energy_saved_today` | Sensor | **on** | kWh saved today |
| `sensor.heat_manager_efficiency_score` | Sensor | disabled | Daily score 0–100 (DIAGNOSTIC) |
| `sensor.heat_manager_<room>_state` | Sensor | **on** | normal / window_open / away / pre_heat / override |
| `sensor.heat_manager_<room>_window_duration` | Sensor | disabled | Minutes window open today (DIAGNOSTIC) |
| `binary_sensor.heat_manager_any_window_open` | Binary | **on** | True when any window is open |
| `binary_sensor.heat_manager_heating_wasted` | Binary | disabled | Window open + heating running (DIAGNOSTIC) |
| `binary_sensor.heat_manager_<room>_window` | Binary | disabled | Per-room window open (DIAGNOSTIC) |
| `binary_sensor.heat_manager_<room>_mold_risk` | Binary | **on** | Mold risk (RH ≥ 70 % + T ≤ dewpoint + 1 °C) — requires `humidity_sensor` |
| `switch.heat_manager_<room>_override` | Switch | disabled | Manual override per room |

---

## Troubleshooting

### Heating not turning on after arriving home

1. Check that the person entity shows `home` in Developer Tools → States.
2. Check that all window sensors show `off` (closed).
3. Check `select.heat_manager_controller_state` — should be `on`.
4. Check the `auto_off_reason` attribute on the controller select.
5. Enable debug logging and check HA logs.

### PID under-heating a Zigbee TRV room

The TRV's built-in sensor sits on the hot valve body and reads 1–3 °C above actual room temperature. Fix: add a wall-mounted probe (e.g. Aqara, Sonoff SNZB-02) and set it as `room_temp_sensor` for that room.

### Netatmo unavailable banner in panel

The panel shows a cloud status banner when all climate entities are `unavailable` or when entity data is stale (≥ 10 min). Check [health.netatmo.com](https://health.netatmo.com) for known outages. The banner can be dismissed and will reappear automatically if the issue persists.

### Enable debug logging

```yaml
logger:
  default: warning
  logs:
    custom_components.heat_manager: debug
```

---

## Known limitations

- Pre-heat requires a `sensor.<person>_travel_time_home` sensor in HA.
- Energy waste uses Netatmo's `heating_power_request` when available; falls back to Δtemp proxy for other rooms.
- PID via HomeKit requires the Netatmo Relay paired as HomeKit Controller in HA.
- CO₂ waste weighting uses a fixed 50 % reduction above 900 ppm — not yet configurable via the UI.
- Valve protection runs once per week at 02:00–03:00 local time, only when the controller is OFF.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

---

## License

MIT — see [LICENSE](LICENSE).
