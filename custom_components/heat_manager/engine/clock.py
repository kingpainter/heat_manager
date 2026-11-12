"""Clock for the engines — pure, no Home Assistant import.

Engines must not import ``homeassistant.*`` (architecture rule 3.1), but
several need "now". This module gives them ``utcnow()`` and ``local_now()``.
At setup the coordinator hands in Home Assistant's own functions
(``dt_util.utcnow`` / ``dt_util.now``) via :func:`use_providers`, so engines
see exactly the time — and the configured time zone — Home Assistant uses.
Before that (unit tests) the defaults are UTC, which matches Home
Assistant's own default time zone.

Tests that need a fixed time keep patching the name in the engine module
(e.g. ``engine.season_engine.local_now``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

_utcnow_provider: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731
_local_now_provider: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def use_providers(
    *,
    utcnow: Callable[[], datetime],
    local_now: Callable[[], datetime],
) -> None:
    """Use Home Assistant's time functions (called once by the coordinator)."""
    global _utcnow_provider, _local_now_provider  # noqa: PLW0603
    _utcnow_provider = utcnow
    _local_now_provider = local_now


def utcnow() -> datetime:
    """Current time, timezone-aware UTC."""
    return _utcnow_provider()


def local_now() -> datetime:
    """Current time in Home Assistant's configured time zone."""
    return _local_now_provider()
