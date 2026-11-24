"""Regenerate the screenshots in docs/ with headless Chromium (Playwright for Python).

    python tools/screenshots.py                    # writes the README's screenshots to docs/
    python tools/screenshots.py OUT_DIR --dark     # review copies (plus full-page views) elsewhere, in dark mode
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_URL = (ROOT / "app" / "index.html").as_uri()


def main(out_dir, dark=False, scale=2, review=False):
    """Write the screenshots used in the README; review=True adds full-page views for checking."""
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "-dark" if dark else ""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        desktop = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=scale, color_scheme="dark" if dark else "light")
        desktop.goto(APP_URL)
        desktop.screenshot(path=str(out / ("overview%s.png" % suffix)), clip={"x": 0, "y": 0, "width": 1280, "height": 900})
        if review:
            desktop.screenshot(path=str(out / ("full-page%s.png" % suffix)), full_page=True)
        for section, name in (("#map-title", "ladder"), ("#outlook-title", "outlook"), ("#card-title", "card-and-robustness")):
            box = desktop.locator(section).locator("xpath=ancestor::section[1]")
            if name == "card-and-robustness":
                box = desktop.locator(section).locator("xpath=ancestor::div[contains(@class,'grid-2')][1]")
            box.screenshot(path=str(out / ("%s%s.png" % (name, suffix))))
        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=scale, color_scheme="dark" if dark else "light")
        phone.goto(APP_URL)
        if review:
            phone.screenshot(path=str(out / ("phone-full%s.png" % suffix)), full_page=True)
        phone.evaluate("document.getElementById('summary-title').scrollIntoView({block: 'start'})")
        phone.screenshot(path=str(out / ("phone%s.png" % suffix)))
        browser.close()
    print("Screenshots written to %s" % out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    main(args[0] if args else ROOT / "docs", dark="--dark" in sys.argv, scale=1 if args else 2, review=bool(args))
