"""Take the README screenshots of the app with the sample data (needs Playwright for Python).

Run:  python tools/screenshots.py
"""

import os

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "file://" + os.path.join(ROOT, "app", "index.html")
DOCS = os.path.join(ROOT, "docs")

# (file name, view, viewport width, viewport height, scroll to this selector first, open details)
SHOTS = [
    ("01-first-screen.png", "regulars", 1280, 900, None, False),
    ("02-regular-payments.png", "regulars", 1280, 1100, "#regulars-body .manifold", True),
    ("03-statements.png", "statements", 1280, 1100, "#statements-body .files", False),
    ("04-calendar.png", "calendar", 1280, 1100, "#calendar-body .payday", False),
    ("05-plan.png", "plan", 1280, 1100, "#plan-body .recheck", False),
    ("06-phone.png", "regulars", 390, 844, "#regulars-body .manifold", False),
]


def shrink(path):
    """Reduce the PNG to a palette image where that keeps it sharp, so the repository stays small."""
    try:
        from PIL import Image
    except ImportError:
        return
    im = Image.open(path).convert("RGB")
    im.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)


def main():
    os.makedirs(DOCS, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, view, width, height, anchor, open_details in SHOTS:
            page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=2)
            page.goto(URL)
            page.wait_for_selector(".reg")
            page.add_style_tag(content=".drip{animation:none!important;opacity:1!important}")
            page.click("#tab-" + view)
            if open_details:
                page.locator(".reg", has_text="Hilltop Broadband").locator("summary").click()
            if anchor:
                page.evaluate("""sel => { const el = document.querySelector(sel); const nav = document.querySelector('.pipe-nav');
                    window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - nav.offsetHeight - 16); }""", anchor)
            page.wait_for_timeout(300)
            path = os.path.join(DOCS, name)
            page.screenshot(path=path)
            shrink(path)
            page.close()
            print("Wrote docs/" + name)
        browser.close()


if __name__ == "__main__":
    main()
