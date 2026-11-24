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
        page.screenshot(path=str(OUT / "desktop.png"))
        # Second view: a stress test, the workflow comparison and the robustness check.
        page.fill("#p-driftAt", "80")
        page.dispatch_event("#p-driftAt", "input")
        page.wait_for_timeout(500)
        page.click("#robust-run")
        page.wait_for_selector("#robust-chart .tornado-row")
        height = page.evaluate("document.documentElement.scrollHeight")
        page.set_viewport_size({"width": 1280, "height": height})
        page.wait_for_timeout(400)
        box = page.evaluate("""() => {
            const top = document.getElementById('chart-time').closest('.card').getBoundingClientRect();
            const end = document.getElementById('robust-chart').closest('.card').getBoundingClientRect();
            return { x: top.left - 8, y: top.top + window.scrollY - 8, width: top.width + 16, height: end.bottom - top.top + 16 };
        }""")
        page.screenshot(path=str(OUT / "stress-test.png"), clip=box)
        page.close()
        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        phone.goto(APP)
        phone.wait_for_selector("#verdict h2")
        phone.wait_for_timeout(300)
        phone.screenshot(path=str(OUT / "phone.png"))
        browser.close()
    print("Wrote docs/desktop.png, docs/stress-test.png and docs/phone.png")


if __name__ == "__main__":
    main()
