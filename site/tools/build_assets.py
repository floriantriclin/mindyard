# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regenerate og.png, apple-touch-icon.png and favicon.ico from og.html and icon.svg.

Usage: uv run --with playwright python site/tools/build_assets.py
Needs a Chromium installed for Playwright (``playwright install chromium``), or its
path in ``CHROMIUM`` when the installed build does not match the Playwright version.
"""

import os
import struct
from pathlib import Path

from playwright.sync_api import Browser, sync_playwright

SITE = Path(__file__).resolve().parent.parent


def icon(browser: Browser, svg: str, size: int) -> bytes:
    page = browser.new_page(viewport={"width": size, "height": size})
    page.set_content(
        f"<style>body{{margin:0}}svg{{width:{size}px;height:{size}px;display:block}}</style>{svg}"
    )
    png = page.screenshot(omit_background=True)
    page.close()
    return png


def ico(png: bytes, size: int) -> bytes:
    """A single PNG image wrapped in an ICO container."""
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), 6 + 16)
    return header + entry + png


def main() -> None:
    svg = (SITE / "icon.svg").read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"))
        page = browser.new_page(viewport={"width": 1200, "height": 630})
        page.goto((SITE / "tools" / "og.html").as_uri())
        page.screenshot(path=SITE / "og.png")
        # iOS rounds the corners itself: a square icon.
        square = svg.replace('rx="20"', 'rx="0"')
        (SITE / "apple-touch-icon.png").write_bytes(icon(browser, square, 180))
        (SITE / "favicon.ico").write_bytes(ico(icon(browser, svg, 32), 32))
        browser.close()


if __name__ == "__main__":
    main()
