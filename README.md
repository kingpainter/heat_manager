# Heat Manager

**Intelligent heating control for Home Assistant.**

Heat Manager replaces manual YAML automations with a fully configurable
custom integration. It manages presence-based heating, open window detection,
pre-heating on arrival, and seasonal on/off control — all from the UI.

[![Version](https://img.shields.io/badge/version-0.2.9-blue)](https://github.com/kingpainter/heat-manager/releases)
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
- **Window detection** — per-room state machine, fixes all 4 known YAML bugs
- **CO₂-aware window notifications** — open window messages include current CO₂ and context ("ventilation" vs "heat loss")
- **Season engine** — AUTO mode detects Winter/Summer from outdoor temperature history
- **Adaptive away temperature** — warmer setpoint on mild days, cooler on cold days
- **Local outdoor temperature sensor** — optional dedicated sensor overrides weather entity for more accurate microclimate data
- **ON / PAUSE / OFF controller** — manual and automatic (season + outdoor temp)
- **Pre-heat engine** — starts heating before you arrive using `sensor.<person>_travel_time_home`
- **PID controller** — discrete-time PI controller sends proportional setpoints to TRVs every 60 seconds, replacing binary on/off with smooth graduated heating
- **External room temperature sensor** — optional per-room probe for PID feedback, recommended for Zigbee TRVs whose built-in sensor reads high on the radiator body
- **Netatmo HomeKit local path** — PID setpoints written directly to the Netatmo Relay via HomeKit Accessory Protocol on LAN (<100 ms, no cloud), keeping Netatmo's own schedule system intact
- **Energy waste tracking** — uses Netatmo's real `heating_power_request` (0–100 %) × room wattage for accurate kWh; CO₂-weighted so purposeful ventilation counts as reduced waste; falls back to Δtemp proxy for non-Netatmo rooms
- **Energy savings tracking** — estimates kWh saved from away mode using last-known heating power as baseline
- **Efficiency score** — daily 0–100 score based on waste vs. savings
- **Sidebar panel** — Heat Manager panel with 4 tabs: Overview, Rooms, History, Configuration
- **Lovelace card** — bundled custom card, auto-registered in the card picker
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
| `weather_entity` | entity | — | Weather entity for outdoor temperature and season auto-detection |
| `outdoor_temp_sensor` | entity | — | **Optional.** Local outdoor temperature sensor (e.g. Netatmo outdoor module, Aqara). Overrides the weather entity temperature for adaptive away setpoint and season detection. |
| `notify_service` | string | — | HA notify service, e.g. `notify.mobile_app_my_phone` |
| `away_temp_mild` | °C | 17.0 | Away setpoint when outdoor temp is above the mild threshold |
| `away_temp_cold` | °C | 15.0 | Away setpoint when outdoor temp is below the mild threshold |
| `mild_threshold` | °C | 8.0 | Boundary between "mild" and "cold" weather |
| `grace_day_min` | min | 30 | How long to wait after everyone leaves before switching to away (daytime) |
| `grace_night_min` | min | 15 | Same, but at night (23:00–07:00) |
| `auto_off_temp_threshold` | °C | 18.0 | Outdoor temperature above which the controller auto-turns off |
| `auto_off_temp_days` | days | 5 | Consecutive days above threshold before auto-off fires |

### Step 2 — Rooms (repeatable)

Add one entry per room. You can add as many rooms as needed.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `room_name` | string | — | Display name (e.g. "Kitchen") |
| `climate_entity` | entity | — | Cloud/primary climate entity. Used for preset_mode writes and schedule setpoint reads |
| `homekit_climate_entity` | entity | — | **Optional.** HomeKit local entity (Netatmo Relay via HAP). PID setpoints are written here directly over LAN. Recommended for Netatmo NRV users |
| `window_sensors` | entity list | [] | Window and/or door sensors for this room |
| `window_delay_min` | min | 5 | Minutes a window must be open before heating drops |
| `away_temp_override` | °C | 10.0 | Frost-guard floor temperature when window opens |
| `room_wattage` | W | 1000 | Rated heating power for energy calculations (use with `heating_power_request`) |
| `co2_sensor` | entity | — | **Optional.** CO₂ sensor for this room. When set, window notifications include current CO₂ and indicate whether the open window is purposeful ventilation or unnecessary heat loss. Also reduces waste attribution in the energy score when CO₂ is elevated. |
| `room_temp_sensor` | entity | — | **Optional.** Independent room temperature probe for PID feedback. Recommended for Zigbee TRVs whose built-in sensor sits on the hot radiator body (typically reads 1–3 °C above actual room temperature). |

### Step 3 — Persons (repeatable)

Add one entry per person. Persons without device tracking (e.g. a household
member without a smartphone) can be added with tracking disabled — they follow
the house's global presence state.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `person_entity` | entity | — | The `person.*` entity |
| `person_tracking` | bool | true | Enable presence tracking. Set false for non-tracked persons |
| `preheat_lead_time_min` | min | 20 | How many minutes before ETA to start pre-heating |

### Step 4 — Notifications

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `notify_presence` | bool | true | Notify when heating switches due to presence |
| `notify_windows` | bool | true | Notify when a window causes heating to drop |
| `notify_window_warning_30` | bool | true | Send a warning if a window has been open 30+ minutes |
| `notify_preheat` | bool | true | Notify when pre-heat starts |
| `energy_tracking` | bool | true | Enable the energy waste sensor |

### Post-setup options

After setup, click **Configure** on the integration card to:
- Edit global settings
- Add or delete rooms
- Add or delete persons
- Change notification preferences

---

## CO₂-aware window notifications

When a `co2_sensor` is configured for a room, all window-related notifications
include the current CO₂ level and a short contextual label:

- CO₂ ≥ 900 ppm → `(CO₂: 1380 ppm — ventilation)` — the window is doing useful work
- CO₂ < 900 ppm → `(CO₂: 640 ppm — heat loss)` — unnecessary heat loss

The same threshold also affects the energy waste calculation: when CO₂ is elevated,
the `energy_wasted_today` sensor counts the open-window period at 50 % weight so that
necessary ventilation does not unfairly penalise the efficiency score.

---

## Room temperature sensor (PID accuracy)

Zigbee TRVs via Z2M have a known accuracy limitation: their built-in temperature
probe sits on the radiator body and typically reads 1–3 °C higher than the actual
room air temperature. This causes the PID controller to under-heat — it thinks the
room is warmer than it is.

Setting `room_temp_sensor` to an independent room probe (e.g. a wall-mounted Aqara
sensor) fixes this. Heat Manager then reads `current_temperature` from the external
probe instead of the TRV, and PID regulation becomes significantly more accurate.

Netatmo rooms can also benefit if the NRV is positioned poorly, but the improvement
is typically smaller since the Netatmo probe is more decoupled from the valve body.

---

## Services

### `heat_manager.set_controller_state`

Manually set the controller to `on`, `pause`, or `off`.

```yaml
action: heat_manager.set_controller_state
data:
  state: "off"
```

### `heat_manager.pause`

Pause all logic for a specified duration. Room states are preserved.

```yaml
action: heat_manager.pause
data:
  duration_minutes: 60
```

### `heat_manager.resume`

Immediately resume from a pause back to On.

```yaml
action: heat_manager.resume
```

### `heat_manager.force_room_on`

Force a specific room back to schedule mode, bypassing window/away state.

```yaml
action: heat_manager.force_room_on
data:
  room_name: "Kitchen"
```

---

## Entities

All entities are created automatically when Heat Manager is set up.
Diagnostic and configuration entities are disabled by default — enable them
in Settings → Devices & Services → Heat Manager → entities.

| Entity | Type | Default | Description |
|--------|------|---------|-------------|
| `select.heat_manager_controller_state` | Select | **on** | On / Pause / Off — main control |
| `select.heat_manager_season_mode` | Select | disabled | Auto / Winter / Summer (CONFIG) |
| `sensor.heat_manager_pause_remaining` | Sensor | disabled | Minutes left in pause (DIAGNOSTIC) |
| `sensor.heat_manager_energy_wasted_today` | Sensor | **on** | Estimated kWh wasted today (CO₂-weighted) |
| `sensor.heat_manager_energy_saved_today` | Sensor | **on** | Estimated kWh saved today |
| `sensor.heat_manager_efficiency_score` | Sensor | disabled | Daily score 0–100 (DIAGNOSTIC) |
| `sensor.heat_manager_<room>_state` | Sensor | **on** | Per-room: normal / window_open / away / pre_heat / override |
| `sensor.heat_manager_<room>_window_duration` | Sensor | disabled | Minutes window open today (DIAGNOSTIC) |
| `binary_sensor.heat_manager_any_window_open` | Binary | **on** | True when any window is open |
| `binary_sensor.heat_manager_heating_wasted` | Binary | disabled | Window open + heating running (DIAGNOSTIC) |
| `binary_sensor.heat_manager_<room>_window` | Binary | disabled | Per-room window open (DIAGNOSTIC) |
| `switch.heat_manager_<room>_override` | Switch | disabled | Manual override per room (CONFIG) |

---

## Pre-heat setup

Pre-heat starts automatically when a person's travel time sensor drops below
their configured lead time. No additional setup is required beyond creating the
travel time sensor.

Create a template sensor named after the person's entity ID:

```yaml
# For person.flemming → sensor.flemming_travel_time_home
template:
  - sensor:
      - name: "flemming_travel_time_home"
        unit_of_measurement: "s"
        state: >
          {{ state_attr('sensor.google_travel_time', 'duration_in_traffic') | int(0) * 60 }}
```

Or use the [Google Travel Time](https://www.home-assistant.io/integrations/google_travel_time/)
or [Waze Travel Time](https://www.home-assistant.io/integrations/waze_travel_time/) integration
and create a template sensor from it.

---

## Automation examples

### Pause heating with a voice command

```yaml
automation:
  trigger:
    - trigger: conversation
      command: "Pause heating for an hour"
  action:
    - action: heat_manager.pause
      data:
        duration_minutes: 60
```

### Dashboard button to force a room on

```yaml
# tap_action on a button card in Lovelace:
tap_action:
  action: call-service
  service: heat_manager.force_room_on
  data:
    room_name: "Living room"
```

### Alert when efficiency score drops below 70

```yaml
automation:
  trigger:
    - trigger: numeric_state
      entity_id: sensor.heat_manager_efficiency_score
      below: 70
  action:
    - action: notify.mobile_app_my_phone
      data:
        title: "Heat Manager"
        message: "Efficiency score dropped below 70 — check for open windows."
```

---

## Troubleshooting

### Heating not turning on after arriving home

1. Check that the person entity shows `home` in Developer Tools → States.
2. Check that all window sensors for that room show `off` (closed).
3. Check `select.heat_manager_controller_state` — should be `on`.
4. Check `auto_off_reason` attribute on the controller select — if it shows
   `season` or `temperature` the controller auto-turned off.
5. Enable debug logging (see below) and check the HA logs.

### Controller auto-turned off unexpectedly

Check the `auto_off_reason` attribute on `select.heat_manager_controller_state`:
- `season` — season mode was set to Summer, or SeasonEngine detected Summer automatically.
- `temperature` — outdoor temp exceeded the threshold for the configured number of days.
- `none` — turned off manually by you or an automation.

### PID under-heating a Zigbee TRV room

This is the radiator-probe problem. The TRV's built-in sensor sits on the hot
valve body and reports a temperature 1–3 °C higher than the actual room. The PID
thinks the room is warm enough and keeps output low.

Fix: add an independent wall-mounted temperature sensor (e.g. Aqara TVOC, Sonoff
SNZB-02) and set it as `room_temp_sensor` for that room in Heat Manager options.

### Entities not showing in HA

1. Confirm the integration loaded: Settings → Devices & Services → Heat Manager.
2. Check that the integration is not in a retry loop (yellow warning icon).
3. If climate entities were unavailable at startup, HA will retry automatically.
4. Check HA logs for errors from `custom_components.heat_manager`.

### Card not appearing in Lovelace card picker

1. Go to Settings → Dashboards → Resources — look for `heat-manager-card`.
2. If there are duplicate entries, delete them all and restart HA.
3. Hard-refresh the browser: Ctrl+Shift+R (Windows) / Cmd+Shift+R (Mac).

### Enable debug logging

Add to `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.heat_manager: debug
```

---

## Known limitations

- Pre-heat requires a `sensor.<person>_travel_time_home` sensor in HA. Without it
  the engine is a no-op.
- Energy waste and savings use Netatmo's `heating_power_request` when available (accurate
  for typical panel radiators). For non-Netatmo rooms the Δtemp × constant proxy is used.
- PID via HomeKit requires the Netatmo Relay paired as HomeKit Controller in HA. Without
  `homekit_climate_entity` configured, PID is silently skipped and Netatmo's own MPC
  remains in full control.
- Non-tracked persons (tracking disabled) always follow the house global state
  and cannot trigger room-level pre-heat individually.
- Daily energy history resets on HA restart — persistent storage across restarts
  is planned for a future version.
- CO₂ waste weighting uses a fixed 50 % reduction above 900 ppm. The threshold is
  not currently configurable via the UI.

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

---

## License

MIT — see [LICENSE](LICENSE).
