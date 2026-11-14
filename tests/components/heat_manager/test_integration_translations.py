"""Integration translations (config flow, entities, repairs) stay complete.

Home Assistant loads only ``translations/<language>.json`` for a custom
integration; ``strings.json`` is never read at runtime. Until v0.72.1,
``translations/en.json`` lacked 14 keys that ``strings.json`` had (door
fields in the room steps and the ``persistent_issue`` repair), so English
users saw unlabelled fields and an untitled repair.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_INTEGRATION = (
    Path(__file__).resolve().parents[3] / "custom_components" / "heat_manager"
)
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _load(relative: str) -> Any:
    return json.loads((_INTEGRATION / relative).read_text(encoding="utf-8"))


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{prefix}{key}."))
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def test_english_translation_matches_strings_json() -> None:
    """translations/en.json is the runtime copy of strings.json."""
    assert _load("translations/en.json") == _load("strings.json")


def test_every_translation_has_the_same_keys_and_placeholders() -> None:
    """Each language file covers every key with the same placeholders."""
    source = _flatten(_load("strings.json"))
    for path in sorted((_INTEGRATION / "translations").glob("*.json")):
        translated = _flatten(_load(f"translations/{path.name}"))
        assert set(translated) == set(source), path.name
        for key, text in source.items():
            assert set(_PLACEHOLDER.findall(translated[key])) == set(
                _PLACEHOLDER.findall(text)
            ), f"{path.name}: {key}"
