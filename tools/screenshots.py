"""Take the screenshots used in the README.

    python tools/screenshots.py

Needs Playwright for Python with Chromium. Writes PNG files to docs/.
The date is fixed so the pictures match the README text.
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP = (ROOT / "app" / "index.html").as_uri()
OUT = ROOT / "docs"
AS_OF = "2026-11-24"


def prepare(page, preset="shortlister", register=False):
    page.goto(APP)
    page.evaluate("window.localStorage.clear()")
    page.reload()
    page.fill("#a-asof", AS_OF)
    page.dispatch_event("#a-asof", "change")
    page.select_option("#preset", preset)
    if register:
        page.click("#reg-examples")
        page.evaluate("document.getElementById('reg-msg').textContent = ''")
    page.evaluate("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)")


def main(argv):
    OUT.mkdir(exist_ok=True)
    only = set(argv)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        shots = [
            ("desktop.png", dict(viewport={"width": 1280, "height": 900}, device_scale_factor=2), "shortlister", False, None),
            ("phone.png", dict(viewport={"width": 390, "height": 844}, device_scale_factor=2), "transcript", False, None),
            ("dark.png", dict(viewport={"width": 1280, "height": 900}, device_scale_factor=2, color_scheme="dark"), "benefits", False, None),
            ("register.png", dict(viewport={"width": 1280, "height": 900}, device_scale_factor=2), "shortlister", True, "#reg-title"),
            ("pivots.png", dict(viewport={"width": 1280, "height": 900}, device_scale_factor=2), "transcript", False, "#piv-title"),
        ]
        for name, ctx, preset, register, anchor in shots:
            if only and name not in only:
                continue
            context = browser.new_context(locale="en-GB", **ctx)
            page = context.new_page()
            prepare(page, preset, register)
            if anchor:
                page.locator(anchor).scroll_into_view_if_needed()
                page.evaluate("(sel) => { const e = document.querySelector(sel).closest('section'); window.scrollTo(0, e.getBoundingClientRect().top + window.scrollY - 16); }", anchor)
            page.wait_for_timeout(150)
            page.screenshot(path=str(OUT / name))
            print("Wrote docs/%s" % name)
            context.close()
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
