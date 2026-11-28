"""Take the README screenshots in docs/ with headless Chromium (Playwright for Python).

Run:  python tools/screenshots.py
"""

import os
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = 'file://' + os.path.join(ROOT, 'app', 'index.html')
DOCS = os.path.join(ROOT, 'docs')


def section(page, selector, path, pad=12):
    box = page.locator(selector).first.bounding_box()
    box['y'] += page.evaluate('window.scrollY')
    page.screenshot(path=path, full_page=True, clip={'x': max(0, box['x'] - pad), 'y': max(0, box['y'] - pad), 'width': box['width'] + 2 * pad,
                                                     'height': min(box['height'] + 2 * pad, 1500)})


def main():
    os.makedirs(DOCS, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        page.goto(URL)
        page.wait_for_selector('#review-sheet')
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(DOCS, '01-first-screen.png'))
        section(page, '#review-sheet', os.path.join(DOCS, '02-weekly-review.png'))
        page.select_option('#rv-week', 'all')
        page.wait_for_timeout(200)
        box = page.locator('#equity-chart').bounding_box()
        box['y'] += page.evaluate('window.scrollY')
        page.screenshot(path=os.path.join(DOCS, '03-equity-and-breakdowns.png'), full_page=True,
                        clip={'x': 40, 'y': box['y'] - 120, 'width': 1200, 'height': 1250})
        page.click('#tab-trades')
        page.check('#tr-needs')
        page.click('.trade-row >> nth=1')
        page.wait_for_timeout(200)
        section(page, '.split', os.path.join(DOCS, '04-trade-journal.png'))
        page.click('#tab-fills')
        page.click('details.skipped >> nth=1')
        section(page, '.sources', os.path.join(DOCS, '05-fills-import.png'))
        page.click('#tab-rules')
        section(page, '#view-rules .grid-2', os.path.join(DOCS, '06-rules-and-sizing.png'))
        phone = browser.new_page(viewport={'width': 390, 'height': 844}, device_scale_factor=2)
        phone.goto(URL)
        phone.wait_for_selector('#review-sheet')
        phone.wait_for_timeout(400)
        phone.screenshot(path=os.path.join(DOCS, '07-phone.png'))
        # The companion's team review, from the sample team folder.
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, os.path.join(ROOT, 'companion', 'round_trips.py'), 'team', os.path.join(ROOT, 'data', 'team'), '--out', tmp],
                           check=True, capture_output=True)
            team = browser.new_page(viewport={'width': 1200, 'height': 900})
            team.goto('file://' + os.path.join(tmp, 'team-review.html'))
            team.screenshot(path=os.path.join(DOCS, '08-team-review.png'))
        browser.close()
    print('Wrote the screenshots to docs/')


if __name__ == '__main__':
    main()
