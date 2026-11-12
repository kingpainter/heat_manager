"""
Heat Manager — Netatmo backend adapter (v0.61.0)

Heat Manager drives Netatmo radiator valves through whichever Home Assistant
integration owns the valve's climate entity:

  netatmo  — the core Netatmo integration (cloud, polled)
  net_trv  — NET-TRV, the custom integration from the netatmo-energy project
             (cloud + webhook push, more attributes, same service names under
             the net_trv domain)

Both expose the same climate services (set_temperature / set_preset_mode /
set_hvac_mode), so most of Heat Manager does not care which one is in use.
This module is the single place that knows the difference. It is pure —
no homeassistant imports — so it is testable without a running HA; the
coordinator feeds it entity-registry platforms and config-entry domains.

Capabilities (open_window, setpoint_end_time, valve position, ...) are
deliberately NOT hard-coded per backend here: callers check whether the
attribute or sensor actually exists on the entity, so a backend that gains
a feature later just works.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class NetatmoBackend(StrEnum):
    """Integration that owns a Netatmo valve's climate entity.

    Values are the integrations' HA domains, which are also the entity
    registry `platform` of their entities.
    """

    CORE = "netatmo"
    NET_TRV = "net_trv"


# Preference order for automatic selection: NET-TRV first (push updates,
# 0.1 °C, more attributes), core as the fallback.
AUTO_PREFERENCE: tuple[NetatmoBackend, ...] = (
    NetatmoBackend.NET_TRV,
    NetatmoBackend.CORE,
)

# Summary values for a room / installation (see summarize_backends()).
BACKEND_SUMMARY_NONE = "none"
BACKEND_SUMMARY_MIXED = "mixed"


def resolve_backend(platform: str | None) -> NetatmoBackend | None:
    """Map an entity-registry platform to a Netatmo backend.

    Returns None for anything that is not a Netatmo integration (a Zigbee
    TRV, a HomeKit entity, an entity missing from the registry, ...).
    """
    if not platform:
        return None
    try:
        return NetatmoBackend(platform)
    except ValueError:
        return None


def available_backends(installed_domains: Iterable[str]) -> set[NetatmoBackend]:
    """Netatmo backends among the domains that have a config entry."""
    found: set[NetatmoBackend] = set()
    for domain in installed_domains:
        backend = resolve_backend(domain)
        if backend is not None:
            found.add(backend)
    return found


def effective_backend(
    choice: str | None, available: Iterable[NetatmoBackend]
) -> NetatmoBackend | None:
    """Backend to use for a global choice ("auto", "netatmo", "net_trv").

    "auto" (or no choice) picks the first available backend in
    AUTO_PREFERENCE. An explicit choice is returned only if that backend is
    actually available; otherwise None, which callers surface as a repair.
    """
    avail = set(available)
    explicit = resolve_backend(choice)
    if explicit is not None:
        return explicit if explicit in avail else None
    for backend in AUTO_PREFERENCE:
        if backend in avail:
            return backend
    return None


TEMP_SOURCE_HOMEKIT = "homekit"
TEMP_SOURCE_CLOUD = "cloud"


def temp_source_order(backend: NetatmoBackend | None) -> tuple[str, str]:
    """v0.62.1: which climate entity to read a room's temperature from first
    (after an external room sensor, which always wins).

    NET-TRV pushes changes via webhook in under a second with 0.1 °C
    resolution, so its cloud entity is better than HomeKit's 0.5 °C. Core
    netatmo is polled, so HomeKit (local, live) stays first there — as for
    any non-Netatmo or unknown owner, which keeps pre-0.62.1 behaviour.
    """
    if backend is NetatmoBackend.NET_TRV:
        return (TEMP_SOURCE_CLOUD, TEMP_SOURCE_HOMEKIT)
    return (TEMP_SOURCE_HOMEKIT, TEMP_SOURCE_CLOUD)


def summarize_backends(backends: Iterable[NetatmoBackend | None]) -> str:
    """One label for a set of per-valve backends (ignores non-Netatmo).

    "net_trv" / "netatmo" when all Netatmo valves agree, "mixed" when they
    don't, "none" when there are no Netatmo valves at all.
    """
    found = {b for b in backends if b is not None}
    if not found:
        return BACKEND_SUMMARY_NONE
    if len(found) > 1:
        return BACKEND_SUMMARY_MIXED
    return next(iter(found)).value


def trv_pid_writable(trv_type: str | None, has_homekit: bool) -> bool:
    """v0.61.2: may the PID write setpoints to this TRV?

    A Netatmo valve is only PID-driven through its local HomeKit entity —
    never through the cloud entity (core or NET-TRV), where a PID tick every
    60 s for several rooms would burn Netatmo's 500 calls/hour budget.
    Netatmo TRVs without HomeKit follow the Netatmo schedule instead.
    Non-Netatmo TRVs (Zigbee, ...) are local and always writable. A missing
    trv_type counts as Netatmo, matching the default used everywhere else.
    """
    if (trv_type or "netatmo") == "netatmo":
        return has_homekit
    return True


# ── Valve health (v0.62.0) ────────────────────────────────────────────────────
# Sibling entities on the same device as a Netatmo climate entity, recognised
# by domain + device class / unique-id suffix rather than entity name. NET-TRV
# puts per-valve "<valve>-connectivity", "<valve>-battery_state" and
# "<valve>-battery" on the room device; core netatmo exposes fewer, and a
# role that is not found simply means that check is skipped.

HEALTH_CONNECTIVITY = "connectivity"
HEALTH_BATTERY_STATE = "battery_state"
HEALTH_BATTERY = "battery"

# Netatmo battery_state values that warrant a warning, and the percentage
# threshold used when only a % battery sensor exists.
LOW_BATTERY_STATES = frozenset({"low", "very_low"})
LOW_BATTERY_PERCENT = 20.0


@dataclass(frozen=True)
class SiblingEntity:
    """The registry fields of a sibling entity that role detection needs."""

    entity_id: str
    domain: str
    unique_id: str
    device_class: str | None


def pick_health_entities(siblings: Iterable[SiblingEntity]) -> dict[str, list[str]]:
    """Group sibling entities into health roles (connectivity, battery).

    A room device can hold several valves, so each role is a list.
    """
    roles: dict[str, list[str]] = {}
    for s in siblings:
        if s.domain == "binary_sensor" and s.device_class == "connectivity":
            # The relay's webhook sensor is also a connectivity sensor, but
            # it lives on the relay device, not on a room device.
            if s.unique_id.endswith("-webhook"):
                continue
            roles.setdefault(HEALTH_CONNECTIVITY, []).append(s.entity_id)
        elif s.domain == "sensor" and s.unique_id.endswith("-battery_state"):
            roles.setdefault(HEALTH_BATTERY_STATE, []).append(s.entity_id)
        elif s.domain == "sensor" and s.device_class == "battery":
            roles.setdefault(HEALTH_BATTERY, []).append(s.entity_id)
    return roles


def battery_is_low(battery_state: str | None, battery_percent: str | None) -> bool:
    """True when the valve battery needs attention.

    The coarse Netatmo battery_state is the truth when present; the % value
    is only Netatmo's rough mapping of it and is used as a fallback.
    """
    if battery_state:
        return battery_state in LOW_BATTERY_STATES
    try:
        return battery_percent is not None and float(battery_percent) < (
            LOW_BATTERY_PERCENT
        )
    except (TypeError, ValueError):
        return False
