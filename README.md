# Heat Manager

**Intelligent heating control for Home Assistant.**

Heat Manager replaces manual YAML automations with a fully configurable
custom integration. It manages presence-based heating, open window detection,
pre-heating on arrival, and seasonal on/off control — all from the UI.

[![Version](https://img.shields.io/github/v/release/kingpainter/heat-manager?label=version)](https://github.com/kingpainter/heat-manager/releases)
[![HA min version](https://img.shields.io/badge/Home%20Assistant-%3E%3D2025.1-blue)](https://www.home-assistant.io)
[![License](https://img.shields.io/github/license/kingpainter/heat-manager)](LICENSE)

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
- **Window detection** — per-room state machine, fixes all 4 known bugs from YAML
- **Adaptive away temperature** — warmer setpoint on mild days, cooler on cold days
- **ON / PAUSE / OFF controller** — manual and automatic (season + outdoor temp)
- **Pre-heat engine** — starts heating before you arrive using HA Companion ETA
- **Energy waste tracking** — estimates kWh lost from open windows with heating on
- **Efficiency score** — daily 0–100 score based on waste and unnecessary cycles
- **Lovelace card** — bundled custom card, auto-registered, no manual resource setup
- **Full English + Danish translations**

---

## Requirements

- Home Assistant 2025.1 or newer
- At least one `climate.*` entity per room
- `person.*` entities for presence tracking
- `binary_sensor.*` entities for window/door sensors (optional but recommended)
- `weather.*` entity for adaptive temperature and season auto-detection

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
| `notify_service` | string | — | HA notify service, e.g. `notify.mobile_app_my_phone` |
| `away_temp_mild` | °C | 17.0 | Away setpoint when outdoor temp is above the mild threshold |
| `away_temp_cold` | °C | 15.0 | Away setpoint when outdoor temp is below the mild threshold |
| `mild_threshold` | °C | 8.0 | Boundary between "mild" and "cold" weather |
| `grace_day_min` | min | 30 | How long to wait after everyone leaves before switching to away (daytime) |
| `grace_night_min` | min | 15 | Same, but at night (23:00–07:00) |
| `auto_off_temp_threshold` | °C | 18.0 | Outdoor temperature above which the controller auto-turns off |
| `auto_off_temp_days` | days | 5 | How many consecutive days above threshold before auto-off fires |

### Step 2 — Rooms (repeatable)

Add one entry per room. You can add as many rooms as needed.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `room_name` | string | — | Display name (e.g. "Kitchen") |
| `climate_entity` | entity | — | The climate entity for this room |
| `window_sensors` | entity list | [] | Window and/or door sensors for this room |
| `window_delay_min` | min | 5 | Minutes a window must be open before the heating drops |
| `away_temp_override` | °C | 10.0 | Temperature to set when the window opens in this room |

### Step 3 — Persons (repeatable)

Add one entry per person. Persons without a device tracker (e.g. a household
member without a smartphone) can be added with tracking disabled — they will
follow the house's global presence state.

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

| Entity | Type | Description |
|--------|------|-------------|
| `select.heat_manager_controller_state` | Select | On / Pause / Off — main control |
| `select.heat_manager_season_mode` | Select | Auto / Winter / Summer |
| `sensor.heat_manager_pause_remaining` | Sensor | Minutes left in pause (0 when not paused) |
| `sensor.heat_manager_energy_wasted_today` | Sensor | Estimated kWh wasted today |
| `sensor.heat_manager_efficiency_score` | Sensor | Daily score 0–100 |
| `sensor.heat_manager_preheat_eta` | Sensor | Minutes until pre-heat ETA |
| `sensor.heat_manager_<room>_state` | Sensor | Per-room state: normal / window_open / away / pre_heat |
| `sensor.heat_manager_<room>_window_duration` | Sensor | Minutes window open today |
| `binary_sensor.heat_manager_any_window_open` | Binary | True when any configured window is open |
| `binary_sensor.heat_manager_heating_wasted` | Binary | True when a window is open and heating is running |
| `switch.heat_manager_<room>_override` | Switch | Manual override for a specific room |

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
# In your Lovelace dashboard (tap_action on a button card):
tap_action:
  action: call-service
  service: heat_manager.force_room_on
  data:
    room_name: "Living room"
```

### Turn heating off for the summer automatically

```yaml
# Heat Manager handles this natively via auto-off.
# You can also trigger it manually from an automation:
automation:
  trigger:
    - trigger: numeric_state
      entity_id: sensor.outdoor_temperature
      above: 20
      for:
        days: 7
  action:
    - action: heat_manager.set_controller_state
      data:
        state: "off"
```

---

## Troubleshooting

### Heating not turning on after arriving home

1. Check that the person entity shows `home` in Developer Tools → States.
2. Check that all window sensors for that room show `off` (closed).
3. Check the controller state: `select.heat_manager_controller_state` should be `on`.
4. Enable debug logging (see below) and check the HA logs.

### Controller auto-turned off unexpectedly

Check `auto_off_reason` attribute on `select.heat_manager_controller_state`.
- `season` — your season mode was set to Summer, or auto-detected as Summer.
- `temperature` — outdoor temperature has been above the threshold for the configured number of days.
- `none` — you or another automation turned it off manually.

### Entities not showing in HA

1. Confirm the integration loaded: Settings → Devices & Services → Heat Manager.
2. Check HA logs for errors from `custom_components.heat_manager`.
3. Try removing and re-adding the integration.

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

- Pre-heat engine requires the HA Companion app with location permissions enabled.
- Energy waste calculation is an estimate based on temperature deltas — not a
  real power meter reading.
- Sebastian-style persons (tracking disabled) always follow the house global state
  and cannot trigger room-level pre-heat individually.
- The Lovelace card requires Home Assistant 2025.1+ (uses modern LitElement APIs).

---

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for the full version history.

---

## License

MIT — see [LICENSE](LICENSE).
