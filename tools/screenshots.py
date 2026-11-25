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
        page.wait_for_selector("#robust .prob-row")
        page.screenshot(path=str(DOCS / "desktop.png"))
        page.locator("section:has(#robust)").screenshot(path=str(DOCS / "robustness.png"))
        page.locator("section:has(#frontier)").screenshot(path=str(DOCS / "frontier.png"))
        page.select_option("#example", "billing")
        page.wait_for_timeout(600)
        page.locator("section:has(#ladder)").screenshot(path=str(DOCS / "ladder.png"))
        page.close()
        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        phone.goto(URL)
        phone.wait_for_selector("#summary .tile")
        phone.evaluate("window.scrollTo(0, document.getElementById('summary').getBoundingClientRect().top + window.scrollY - 24)")
        phone.wait_for_timeout(300)
        phone.screenshot(path=str(DOCS / "phone.png"))
        phone.close()
        dark = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=2, color_scheme="dark")
        dark.goto(URL)
        dark.wait_for_selector("#summary .tile")
        dark.screenshot(path=str(DOCS / "dark.png"))
        browser.close()
    print("Wrote desktop, robustness, frontier, ladder, phone and dark screenshots to docs/")


if __name__ == "__main__":
    main()
