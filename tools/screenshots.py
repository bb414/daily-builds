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
        page.wait_for_selector("#headline h2")
        page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / "desktop.png"))
        # Second view: the what-if sweep and the test in other organisations.
        page.click("#sweep-run")
        page.wait_for_function("document.getElementById('sweep-summary').textContent.includes('wins')", timeout=60000)
        page.click("#robust-run")
        page.wait_for_function("document.getElementById('robust-summary').textContent.includes('was best in')", timeout=60000)
        height = page.evaluate("document.documentElement.scrollHeight")
        page.set_viewport_size({"width": 1280, "height": height})
        page.wait_for_timeout(400)
        box = page.evaluate("""() => {
            const top = document.getElementById('sweep-chart').closest('.card').getBoundingClientRect();
            const end = document.getElementById('robust-table').closest('.card').getBoundingClientRect();
            return { x: top.left - 8, y: top.top + window.scrollY - 8, width: top.width + 16, height: end.bottom - top.top + 16 };
        }""")
        page.screenshot(path=str(OUT / "what-if.png"), clip=box)
        page.close()
        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        phone.goto(APP)
        phone.wait_for_selector("#headline h2")
        phone.wait_for_timeout(400)
        phone.screenshot(path=str(OUT / "phone.png"))
        browser.close()
    print("Wrote the screenshots in docs/")


if __name__ == "__main__":
    main()
