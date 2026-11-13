"""Heat Manager coordinator package (split into layers in v0.68.2, T3b).

See base.py for the layer overview. Everything outside this package imports
HeatManagerCoordinator from here.
"""

from __future__ import annotations

from .core import HeatManagerCoordinator

__all__ = ["HeatManagerCoordinator"]
