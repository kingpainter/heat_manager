"""Tests for the panel/card translations (v0.71.0).

English is the default language; every other language in
frontend/translations/ is a translation of en.json. These tests keep the
JavaScript and the JSON files in step:

* every key the panel/card uses with a literal ``_t("key")`` exists in en.json,
* every en.json key is used (literally, or under a dynamic ``_t(`prefix.${…}`)``
  prefix) — no dead strings,
* every translation has exactly the keys of en.json and the same {placeholders},
* the loader falls back to English and rejects odd language codes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.heat_manager import frontend_translations as ft
from custom_components.heat_manager import websocket

ROOT = Path(__file__).resolve().parents[3] / "custom_components" / "heat_manager"
FRONTEND = ROOT / "frontend"
TRANSLATIONS = FRONTEND / "translations"
JS_FILES = [FRONTEND / "heat-manager-panel.js", FRONTEND / "heat-manager-card.js"]

# Any quoted dotted name — catches keys passed straight to _t("…") as well as
# keys picked in a ternary (_t(x ? "a.b" : "a.c")). Only names whose first
# segment is a top-level group of en.json count as translation keys.
_KEY_LITERAL = re.compile(r"""["']([a-z0-9_]+(?:\.[a-z0-9_]+)+)["']""")
_DYNAMIC_PREFIX = re.compile(r"""_(?:t|hmT)\(\s*`([a-z0-9_.]+)\$\{""")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
# Groups rendered by the backend (event log, its reasons, push notifications)
# — checked against the Python source below, not the JavaScript.
_BACKEND_GROUPS = ("event.", "reason.", "notify.")


def _flat(lang: str) -> dict[str, str]:
    data = json.loads((TRANSLATIONS / f"{lang}.json").read_text(encoding="utf-8"))
    return ft.flatten(data)


def _js_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in JS_FILES)


def _languages() -> list[str]:
    return sorted(p.stem for p in TRANSLATIONS.glob("*.json"))


def test_english_and_danish_exist():
    assert {"en", "da"} <= set(_languages())


def _used_keys(en: dict[str, str]) -> set[str]:
    groups = {k.split(".", 1)[0] for k in en}
    return {
        k
        for k in _KEY_LITERAL.findall(_js_source())
        if k.split(".", 1)[0] in groups and not k.startswith(_BACKEND_GROUPS)
    }


def test_every_literal_key_used_in_js_exists_in_english():
    en = _flat("en")
    used = _used_keys(en)
    missing = sorted(used - set(en))
    assert not missing, f"keys used in JS but missing in en.json: {missing}"


def test_every_dynamic_prefix_has_keys():
    en = _flat("en")
    for prefix in set(_DYNAMIC_PREFIX.findall(_js_source())):
        assert any(k.startswith(prefix) for k in en), prefix


def test_no_unused_english_keys():
    en = _flat("en")
    src = _js_source()
    used = _used_keys(en)
    prefixes = tuple(set(_DYNAMIC_PREFIX.findall(src))) + _BACKEND_GROUPS
    unused = sorted(k for k in en if k not in used and not k.startswith(prefixes))
    assert not unused, f"en.json keys never used by the frontend: {unused}"


@pytest.mark.parametrize("lang", [lang for lang in _languages() if lang != "en"])
def test_translation_has_same_keys_and_placeholders(lang):
    en, other = _flat("en"), _flat(lang)
    assert set(other) == set(en), (
        f"{lang}: missing {sorted(set(en) - set(other))}, "
        f"extra {sorted(set(other) - set(en))}"
    )
    for key, text in en.items():
        assert set(_PLACEHOLDER.findall(other[key])) == set(
            _PLACEHOLDER.findall(text)
        ), f"{lang}:{key} placeholders differ"


def test_no_empty_strings():
    for lang in _languages():
        empty = [k for k, v in _flat(lang).items() if not v.strip()]
        assert not empty, f"{lang}: empty strings {empty}"


# ── Loader ───────────────────────────────────────────────────────────────────


def test_flatten_nested():
    assert ft.flatten({"a": {"b": "x", "c": {"d": "y"}}, "e": "z"}) == {
        "a.b": "x",
        "a.c.d": "y",
        "e": "z",
    }


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("da", ["da", "en"]),
        ("da-DK", ["da-DK", "da", "en"]),
        ("pt_BR", ["pt-BR", "pt", "en"]),
        ("en", ["en"]),
        (None, ["en"]),
        ("", ["en"]),
        ("../../etc/passwd", ["en"]),
        ("da/x", ["en"]),
    ],
)
def test_language_candidates(language, expected):
    assert ft.language_candidates(language) == expected


def test_load_falls_back_to_english_per_key(tmp_path):
    (tmp_path / "en.json").write_text(
        json.dumps({"a": "A", "g": {"b": "B"}}), encoding="utf-8"
    )
    (tmp_path / "da.json").write_text(json.dumps({"a": "Å"}), encoding="utf-8")
    used, strings = ft.load_translations("da-DK", tmp_path.as_posix())
    assert used == "da"
    assert strings == {"a": "Å", "g.b": "B"}


def test_load_unknown_language_is_english(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"a": "A"}), encoding="utf-8")
    assert ft.load_translations("xx", tmp_path.as_posix()) == ("en", {"a": "A"})


def test_load_real_danish_is_complete():
    used, strings = ft.load_translations("da")
    assert used == "da"
    assert strings == _flat("da")


# ── WebSocket command ────────────────────────────────────────────────────────


async def test_ws_get_translations_returns_language_and_resources():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    connection = MagicMock()
    await websocket.ws_get_translations.__wrapped__(
        hass,
        connection,
        {"id": 7, "type": "heat_manager/get_translations", "language": "da"},
    )
    msg_id, result = connection.send_result.call_args.args
    assert msg_id == 7
    assert result["language"] == "da"
    assert result["resources"]["tabs.overview"] == "Oversigt"


async def test_ws_get_translations_without_language_is_english():
    hass = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    connection = MagicMock()
    await websocket.ws_get_translations.__wrapped__(
        hass, connection, {"id": 1, "type": "heat_manager/get_translations"}
    )
    _, result = connection.send_result.call_args.args
    assert result["language"] == "en"
    assert result["resources"]["tabs.overview"] == "Overview"


# ── Status-line issues (websocket_payload.build_active_issues) ──────────────


def test_issue_templates_match_english_translations():
    """The backend's English `message` and the frontend's "issue.<key>" text
    are the same string — one can't drift from the other."""
    from custom_components.heat_manager.websocket_payload import ISSUE_TEMPLATES

    en = _flat("en")
    issue_keys = {k.removeprefix("issue.") for k in en if k.startswith("issue.")}
    assert issue_keys == set(ISSUE_TEMPLATES)
    for key, template in ISSUE_TEMPLATES.items():
        assert en[f"issue.{key}"] == template, key


# ── Backend texts: event log, reasons, push notifications (v0.72.0) ─────────


def _py_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in ROOT.rglob("*.py"))


def test_event_keys_match_english_translations():
    from custom_components.heat_manager.messages import EVENT_KEYS

    en = _flat("en")
    assert {k.removeprefix("event.") for k in en if k.startswith("event.")} == set(
        EVENT_KEYS
    )


def test_every_literal_log_message_key_is_registered():
    from custom_components.heat_manager.messages import EVENT_KEYS

    used = set(re.findall(r'log_message\(\s*"(\w+)"', _py_source()))
    assert used, "no log_message() calls found"
    assert used <= set(EVENT_KEYS), sorted(used - set(EVENT_KEYS))


def test_backend_text_keys_exist_and_are_used():
    """Every "notify."/"issue." key the Python code names exists in en.json,
    and every notify/reason key is named somewhere in the Python code
    (window/door texts are picked as f"notify.{kind}_…")."""
    en = _flat("en")
    src = _py_source()
    named = set(re.findall(r"""["'](notify\.\w+|issue\.\w+)["']""", src))
    assert named <= set(en), sorted(named - set(en))
    kind_suffixes = set(re.findall(r'f"notify\.\{kind\}_(\w+)"', src))
    for key in (k for k in en if k.startswith("notify.")):
        name = key.removeprefix("notify.")
        kinded = any(name in (f"window_{x}", f"door_{x}") for x in kind_suffixes)
        assert key in named or kinded, f"{key} is never used by the backend"
    for key in (k for k in en if k.startswith("reason.")):
        name = key.removeprefix("reason.")
        assert f'"{name}"' in src or name in ("window", "door"), (
            f"{key} is never used by the backend"
        )


def test_render_nested_reference_and_missing_key():
    strings = {"a": "Season {season} in {room}", "season.winter": "Winter"}
    assert (
        ft.render(strings, "a", {"season": ft.text_ref("season.winter"), "room": "X"})
        == "Season Winter in X"
    )
    assert ft.render(strings, "missing.key") == "missing.key"
    assert ft.render(strings, "a", {"room": "X"}) == "Season {season} in X"


def test_load_languages_english_and_system_language():
    texts = ft.load_languages(["en", "da", "en"])
    assert set(texts) == {"en", "da"}
    assert texts["da"]["event.boost_stopped"] == "Boost deaktiveret"
