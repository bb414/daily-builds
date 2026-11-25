"""Retake the screenshots in docs/ with headless Chromium (needs Playwright for Python)."""

from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = (ROOT / "app" / "index.html").as_uri()
DOCS = ROOT / "docs"


def main():
    DOCS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1000}, device_scale_factor=2)
        page.goto(URL)
        page.wait_for_selector("#summary .tile")
        page.screenshot(path=str(DOCS / "desktop.png"))
        page.locator("#frontier").scroll_into_view_if_needed()
        page.locator("section:has(#frontier)").screenshot(path=str(DOCS / "frontier.png"))
        page.close()
        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        phone.goto(URL)
        phone.wait_for_selector("#summary .tile")
        phone.locator("#results").scroll_into_view_if_needed()
        phone.screenshot(path=str(DOCS / "phone.png"))
        browser.close()
    print("Wrote docs/desktop.png, docs/frontier.png and docs/phone.png")


if __name__ == "__main__":
    main()
