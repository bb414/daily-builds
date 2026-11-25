"""Regenerates the README screenshots with headless Chromium (Playwright).

    python3 docs/make_screenshots.py
"""

import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "file://" + os.path.join(ROOT, "app", "index.html")
OUT = os.path.join(ROOT, "docs")

SHOTS = [
    # (file, width, tab to open, preset to pick, full page)
    ("applicant.png", 1280, "#tab-applicant", "Four ways in", False),
    ("cohort.png", 1280, "#tab-cohort", None, False),
    ("phone.png", 390, "#tab-applicant", "Held back by a past gap", False),
]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, width, tab, preset, full in SHOTS:
            page = browser.new_page(viewport={"width": width, "height": 1000 if width > 600 else 1600},
                                    device_scale_factor=2 if width > 600 else 3)
            page.emulate_media(color_scheme="light")
            page.goto(URL)
            page.wait_for_selector("#plans .plan")
            if preset:
                page.select_option("#preset", label=preset)
            page.click(tab)
            page.wait_for_timeout(300)
            page.screenshot(path=os.path.join(OUT, name), full_page=full)
            page.close()
            print("Wrote docs/" + name)
        browser.close()


if __name__ == "__main__":
    main()
