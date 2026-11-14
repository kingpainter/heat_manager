"""Heat Manager — translations for the sidebar panel and the Lovelace card.

English is the default language. Every other language is a translation in
``frontend/translations/<language>.json`` with the same keys as ``en.json``.
The files are nested JSON objects; the frontend gets them flattened to
dotted keys (``"overview.rooms_title"``), with English filled in for any key
the requested language lacks — so a partial translation never shows a raw
key.

Served over the WebSocket API (``heat_manager/get_translations``) rather than
as a static file: panel.py registers the panel's static URLs once per Home
Assistant process, so a static translation file could stay cached until the
next restart.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

FALLBACK_LANGUAGE = "en"
TRANSLATIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "frontend", "translations"
)

# BCP 47-ish: "da", "en", "pt-BR", "zh-Hant". Anything else is rejected
# before it is used to build a file name.
_LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")


def flatten(tree: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten a nested translation object to dotted keys."""
    flat: dict[str, str] = {}
    for key, value in tree.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten(value, full))
        else:
            flat[full] = str(value)
    return flat


def language_candidates(language: str | None) -> list[str]:
    """Files to try for ``language``, most specific first, English last.

    "da-DK" → ["da-DK", "da", "en"]; an invalid or missing language → ["en"].
    """
    candidates: list[str] = []
    if language and _LANGUAGE_RE.match(language):
        tag = language.replace("_", "-")
        parts = tag.split("-")
        for i in range(len(parts), 0, -1):
            candidate = "-".join(parts[:i])
            if candidate not in candidates:
                candidates.append(candidate)
    if FALLBACK_LANGUAGE not in candidates:
        candidates.append(FALLBACK_LANGUAGE)
    return candidates


def merge_languages(layers: list[dict[str, str]]) -> dict[str, str]:
    """Merge flattened layers; earlier layers win (most specific first)."""
    merged: dict[str, str] = {}
    for layer in reversed(layers):
        merged.update(layer)
    return merged


def _read_language_file(directory: str, language: str) -> dict[str, str] | None:
    """Flattened content of ``<directory>/<language>.json``, or None."""
    path = os.path.join(directory, f"{language}.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return flatten(data) if isinstance(data, dict) else None


def load_translations(
    language: str | None, directory: str = TRANSLATIONS_DIR
) -> tuple[str, dict[str, str]]:
    """Return (language actually used, flattened strings with English fallback).

    Blocking file I/O — call it from an executor job.
    """
    layers: list[dict[str, str]] = []
    used = FALLBACK_LANGUAGE
    for candidate in language_candidates(language):
        layer = _read_language_file(directory, candidate)
        if layer is None:
            continue
        if not layers:
            used = candidate
        layers.append(layer)
    return used, merge_languages(layers)


_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def render(
    strings: dict[str, str], key: str, params: dict[str, Any] | None = None
) -> str:
    """Text for `key` with {placeholders} filled in from `params`.

    A param value may itself be a reference to another text —
    ``{"key": "<full key>", "params": {...}}`` — rendered in the same
    language (used for parts that need their own wording, e.g. the CO₂/rain
    context after a window notification). An unknown key renders as the key
    itself, so a missing string is visible rather than empty. The frontend's
    ``_t()``/``_hmT()`` do exactly the same.
    """
    template = strings.get(key, key)
    if not params:
        return template

    def _value(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            return match.group(0)
        value = params[name]
        if isinstance(value, dict) and "key" in value:
            return render(strings, str(value["key"]), value.get("params"))
        return str(value)

    return _PLACEHOLDER_RE.sub(_value, template)


def text_ref(key: str, **params: Any) -> dict[str, Any]:
    """A param value that renders another text (see `render`)."""
    return {"key": key, "params": params} if params else {"key": key}


def load_languages(languages: list[str]) -> dict[str, dict[str, str]]:
    """Flattened strings (English fallback) for each language in `languages`.

    Used at setup for the backend's own texts: English for the stored event
    log, and the Home Assistant system language for push notifications.
    Blocking file I/O — call it from an executor job.
    """
    return {lang: load_translations(lang)[1] for lang in dict.fromkeys(languages)}
