"""Takes the README screenshots in docs/ with headless Chromium (Playwright).

Run:  python tools/screenshots.py
"""

import os
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = "file://" + os.path.join(ROOT, "app", "index.html")
DOCS = os.path.join(ROOT, "docs")


def view(page, name, path, clip_height=None):
    page.click("#tab-" + name)
    page.wait_for_timeout(250)
    el = page.locator("#view-" + name)
    box = el.bounding_box()
    page.screenshot(path=path, clip={"x": 0, "y": box["y"] - 70, "width": page.viewport_size["width"],
                                      "height": min(box["height"] + 90, clip_height or 1600)}, full_page=True)


def main():
    os.makedirs(DOCS, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(PAGE)
        page.wait_for_selector(".slip")
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(DOCS, "01-first-screen.png"))
        view(page, "check", os.path.join(DOCS, "02-check.png"), 1500)
        view(page, "refs", os.path.join(DOCS, "03-references.png"), 1500)
        view(page, "changes", os.path.join(DOCS, "04-changes.png"), 1350)
        view(page, "declare", os.path.join(DOCS, "05-declaration.png"), 1250)
        view(page, "copy", os.path.join(DOCS, "06-your-texts.png"), 1350)
        # mark everything to show the signed-off proof
        page.click("#tab-check")
        while page.locator("#view-check li.query.st-unchecked button[data-status=verified]").count():
            page.locator("#view-check li.query.st-unchecked button[data-status=verified]").first.click()
        page.click("#tab-refs")
        while page.locator("#view-refs button[data-status=checked][aria-pressed=false]").count():
            page.locator("#view-refs button[data-status=checked][aria-pressed=false]").first.click()
        page.click("#tab-declare")
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(DOCS, "07-signed-off.png"))
        page.evaluate("localStorage.clear()")
        phone = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
        phone.goto(PAGE)
        phone.wait_for_selector(".slip")
        phone.wait_for_timeout(300)
        phone.screenshot(path=os.path.join(DOCS, "08-phone.png"))
        with tempfile.TemporaryDirectory() as d:
            report = os.path.join(d, "report.html")
            subprocess.run([sys.executable, os.path.join(ROOT, "companion", "checked_by_me.py"), "batch", os.path.join(ROOT, "data", "drafts"),
                            "--notes", os.path.join(ROOT, "data", "notes.md"), "--out", report, "--as-of", "2026-11-28"], check=True, capture_output=True)
            rp = browser.new_page(viewport={"width": 1100, "height": 1000})
            rp.goto("file://" + report)
            rp.screenshot(path=os.path.join(DOCS, "09-batch-report.png"))
        browser.close()
    print("Wrote the screenshots to docs/")


if __name__ == "__main__":
    main()
