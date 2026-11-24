"""Regenerates the README screenshots with headless Chromium: python tools/screenshots.py"""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
APP = (ROOT / "app" / "index.html").as_uri()
OUT = ROOT / "docs"


def main():
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2)
        page.goto(APP)
        page.wait_for_selector("#verdict h2")
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / "desktop.png"), full_page=True)
        page.close()
        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        phone.goto(APP)
        phone.wait_for_selector("#verdict h2")
        phone.wait_for_timeout(300)
        phone.screenshot(path=str(OUT / "phone.png"), full_page=True)
        browser.close()
    print("Wrote docs/desktop.png and docs/phone.png")


if __name__ == "__main__":
    main()
