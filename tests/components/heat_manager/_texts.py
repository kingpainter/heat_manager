"""Test helper: the coordinator's text() rendered in English from en.json.

Engines and coordinator layers build log/notification texts through
coordinator.text(); a bare MagicMock coordinator would return a MagicMock.
Bind this as `coord.text = english_text` where a test looks at the text.
"""

from __future__ import annotations

from typing import Any

from custom_components.heat_manager import frontend_translations as ft

_EN = ft.load_translations("en")[1]


def english_text(key: str, language: str | None = None, **params: Any) -> str:
    return ft.render(_EN, key, params)
