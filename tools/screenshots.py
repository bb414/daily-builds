"""Take the README screenshots of the app (and the companion's report) into docs/.

Run:  python tools/screenshots.py      (needs Playwright for Python and Chromium)
"""

import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, 'docs')
APP = 'file://' + os.path.join(ROOT, 'app', 'index.html')
sys.path.insert(0, os.path.join(ROOT, 'companion'))

from playwright.sync_api import sync_playwright  # noqa: E402


def view(page, name, path, height=1250):
    page.click('#tab-' + name)
    page.wait_for_timeout(250)
    top = page.evaluate("document.querySelector('.sheet').getBoundingClientRect().top + window.scrollY")
    page.screenshot(path=path, clip={'x': 0, 'y': top - 12, 'width': 1280, 'height': height}, full_page=True)


def main():
    os.makedirs(DOCS, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()

        def fresh(width=1280, height=900, scale=1):
            # A new context each time, so nothing saved in the browser carries over.
            pg = b.new_context(viewport={'width': width, 'height': height}, device_scale_factor=scale).new_page()
            pg.goto(APP)
            pg.wait_for_selector('.month')
            return pg

        page = fresh()
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(DOCS, '01-first-screen.png'))
        view(page, 'plan', os.path.join(DOCS, '02-plan.png'), 1400)
        view(page, 'progress', os.path.join(DOCS, '03-progress.png'), 1500)
        page.click('[data-action=replan]')
        page.wait_for_timeout(300)
        top = page.evaluate("document.querySelector('.track-cards').getBoundingClientRect().top + window.scrollY")
        page.screenshot(path=os.path.join(DOCS, '04-after-replan.png'), clip={'x': 0, 'y': top - 60, 'width': 1280, 'height': 760}, full_page=True)
        page = fresh()
        page.click('#banner [data-action=try-messy]')
        page.wait_for_timeout(300)
        view(page, 'exams', os.path.join(DOCS, '05-exams-and-topics.png'), 1150)
        page = fresh()
        view(page, 'time', os.path.join(DOCS, '06-your-time.png'), 1300)
        view(page, 'rules', os.path.join(DOCS, '07-rules.png'), 1100)
        phone = fresh(390, 844, 2)
        phone.wait_for_timeout(300)
        phone.screenshot(path=os.path.join(DOCS, '08-phone.png'))
        from examseason import model as m, report
        proj = m.read_project(open(os.path.join(ROOT, 'data', 'sample-project.json'), encoding='utf-8').read(), m.day_from_ymd(2026, 12, 10))['project']
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'report.html')
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(report.plan_report(proj, m.day_from_ymd(2026, 12, 10)))
            rp = b.new_page(viewport={'width': 1100, 'height': 1000})
            rp.goto('file://' + path)
            rp.screenshot(path=os.path.join(DOCS, '09-companion-report.png'))
        b.close()
    print('Wrote the screenshots to docs/')


if __name__ == '__main__':
    main()
