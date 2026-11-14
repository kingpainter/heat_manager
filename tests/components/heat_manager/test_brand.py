"""Local brand images (HA 2026.3+) use the file names Home Assistant serves.

Home Assistant serves ``custom_components/<domain>/brand/<name>`` only for a
fixed set of names. Until v0.72.2 the 1x icon was named ``icon (1).png``, so
``/api/brands/integration/heat_manager/icon.png`` fell back to the brands CDN,
which has no Heat Manager icon.
"""

from __future__ import annotations

from pathlib import Path

_BRAND = (
    Path(__file__).resolve().parents[3] / "custom_components" / "heat_manager" / "brand"
)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def test_brand_icon_has_the_name_home_assistant_serves() -> None:
    """brand/icon.png exists and is a PNG."""
    icon = _BRAND / "icon.png"
    assert icon.is_file()
    assert icon.read_bytes()[:8] == _PNG_SIGNATURE


def test_high_resolution_icon_is_a_png() -> None:
    """brand/icon@2x.png exists and is a PNG."""
    icon = _BRAND / "icon@2x.png"
    assert icon.is_file()
    assert icon.read_bytes()[:8] == _PNG_SIGNATURE
