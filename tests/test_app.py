"""Drive the browser app in headless Chromium: the sample, uploads (good and bad), the journal, every download,
reopening and merging a saved journal, a frame, a phone and labels.

Skipped cleanly when Playwright or its browser is not installed.
"""

import csv
import io
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'app', 'index.html')
DATA = os.path.join(ROOT, 'data')
URL = 'file://' + APP

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None

# Every control should have a name a screen reader can read out.
UNLABELLED = """() => [...document.querySelectorAll('main input, main select, main textarea, main button, nav button, header button')]
  .filter(el => el.offsetParent !== null && el.type !== 'hidden')
  .filter(el => {
    if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
    if (el.labels && el.labels.length && [...el.labels].some(l => l.textContent.trim())) return false;
    if (el.tagName === 'BUTTON' && el.textContent.trim()) return false;
    return true;
  }).map(el => el.outerHTML.slice(0, 120))"""


@unittest.skipIf(sync_playwright is None, 'Playwright for Python is not installed')
class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover - depends on the machine
            cls.pw.stop()
            raise unittest.SkipTest('Chromium could not start: %s' % exc)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def setUp(self):
        self.context = self.browser.new_context(accept_downloads=True)
        self.errors, self.requests = [], []

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [], 'the page reported errors')
        self.assertEqual(self.requests, [], 'the page tried to reach the network')

    def open(self, width=1280, height=900, url=URL):
        page = self.context.new_page()
        page.set_viewport_size({'width': width, 'height': height})
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.on('console', lambda m: self.errors.append(m.text) if m.type == 'error' else None)
        page.on('request', lambda r: self.requests.append(r.url) if not r.url.startswith(('file:', 'data:', 'blob:')) else None)
        page.goto(url)
        if url == URL:
            page.wait_for_selector('#review-sheet')
        return page

    def download(self, page, selector):
        with page.expect_download() as info:
            page.click(selector)
        path = os.path.join(self.tmp.name, info.value.suggested_filename)
        info.value.save_as(path)
        with open(path, encoding='utf-8-sig') as fh:
            return info.value.suggested_filename, fh.read(), path

    def test_opens_with_the_sample_worked_through(self):
        page = self.open()
        headline = page.inner_text('#headline')
        self.assertIn('+$1,595.71', headline)
        self.assertIn('52%', headline)
        self.assertEqual(page.get_attribute('#tab-review', 'aria-selected'), 'true')
        text = page.input_value('#review-text')
        self.assertTrue(text.startswith('WEEKLY TRADE REVIEW: w/c 23 Nov 2026'))
        self.assertIn('Not financial advice.', text)
        self.assertIn('invented trading-challenge team', page.inner_text('#notice'))
        self.assertEqual(page.text_content('#hero-symbol'), 'GLBM short')
        self.assertIn('not financial advice', page.inner_text('header').lower())
        self.assertTrue(page.is_visible('#equity-chart svg'))

    def test_tabs_work_with_the_keyboard(self):
        page = self.open()
        page.focus('#tab-review')
        page.keyboard.press('ArrowRight')
        self.assertEqual(page.get_attribute('#tab-rules', 'aria-selected'), 'true')
        self.assertTrue(page.is_visible('#view-rules'))
        page.keyboard.press('End')
        self.assertEqual(page.get_attribute('#tab-how', 'aria-selected'), 'true')
        page.keyboard.press('Home')
        self.assertTrue(page.is_visible('#intray'))

    def test_own_files_including_a_bad_one(self):
        page = self.open()
        bad = os.path.join(self.tmp.name, 'statement.csv')
        with open(bad, 'w', encoding='utf-8') as fh:
            fh.write('Name,Score\nA,1\n')
        page.set_input_files('#file-exports', [os.path.join(DATA, 'template.csv'), bad])
        page.wait_for_selector('.source.bad')
        log = page.inner_text('.sources')
        self.assertIn('Could not find a header row', log)
        self.assertIn('template.csv', log)
        self.assertNotIn('invented trading-challenge team', page.inner_text('#notice'))
        page.click('#tab-review')
        self.assertIn('3 closed trades', page.input_value('#review-text'))

    def test_writing_up_a_trade_updates_its_risk_and_r(self):
        page = self.open()
        page.click('#tab-trades')
        page.check('#tr-needs')
        page.click('.trade-row >> nth=0')
        net_text = page.locator('.fig', has_text='Net after fees').inner_text().split('\n')[-1]
        cents = int(net_text.replace('$', '').replace(',', '').replace('.', '').replace('+', ''))
        page.fill('#j-setup', 'Fade the open')
        page.press('#j-setup', 'Tab')
        page.fill('#j-risk', '250')
        page.press('#j-risk', 'Tab')
        r_text = page.locator('.fig', has_text='R multiple').inner_text().split('\n')[-1]
        self.assertEqual(r_text, ('+' if cents > 0 else '') + '%.2fR' % (cents / 25000.0))
        self.assertEqual(page.input_value('#j-setup'), 'Fade the open')
        page.fill('#j-stop', '1')
        page.press('#j-stop', 'Tab')
        self.assertNotIn('no stop', page.inner_text('#trade-ticket'))
        page.check('[data-role="journal-mistake"] >> nth=0')
        page.fill('#j-notes', 'Chased it.')
        page.press('#j-notes', 'Tab')
        self.assertEqual(page.input_value('#j-notes'), 'Chased it.')
        page.click('#tab-review')
        page.click('[data-breakdown="setup"]')
        page.select_option('#rv-week', 'all')
        self.assertIn('Fade the open', page.inner_text('#view-review'))

    def test_every_download(self):
        page = self.open()
        name, text, _ = self.download(page, '[data-action="trades-csv"] >> nth=0')
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertTrue(name.startswith('round-trips-'))
        self.assertEqual(len(rows), 238)
        self.assertEqual(sum(1 for r in rows if r['Status'] == 'Open'), 1)
        name, text, _ = self.download(page, '[data-action="breaches-csv"]')
        self.assertEqual(next(csv.reader(io.StringIO(text)))[0], 'Date')
        name, text, _ = self.download(page, '[data-action="review-txt"]')
        self.assertEqual(name, 'weekly-review-2026-11-23.txt')
        self.assertIn('Net after fees: +$1,595.71', text)
        name, text, _ = self.download(page, '[data-action="save"] >> nth=0')
        data = json.loads(text)
        self.assertEqual(data['app'], 'round-trips')
        self.assertEqual(len(data['fills']), 677)
        page.click('#tab-fills')
        name, text, _ = self.download(page, '[data-action="template"]')
        self.assertEqual(name, 'round-trips-template.csv')
        name, text, _ = self.download(page, '[data-action="fills-csv"]')
        self.assertEqual(len(list(csv.reader(io.StringIO(text)))), 678)
        page.click('#tab-rules')
        self.assertIn('Buy', page.inner_text('#size-out'))

    def test_save_reopen_and_merge_next_weeks_export(self):
        page = self.open()
        page.click('[data-action="clear"] >> nth=0')
        page.set_input_files('#file-exports', os.path.join(DATA, 'weekly', 'export-2026-11-20.csv'))
        page.wait_for_selector('.source')
        _, _, path = self.download(page, '[data-action="save"] >> nth=0')
        page.wait_for_timeout(900)  # the browser copy is saved a moment after each change
        page.close()
        page = self.open()
        self.assertIn('Pick up where you left off', page.inner_text('#notice'))
        page.set_input_files('#file-journal', path)
        page.wait_for_function("document.querySelector('#toast').textContent.indexOf('489 fills') >= 0")
        page.set_input_files('#file-exports', os.path.join(DATA, 'weekly', 'export-2026-11-27.csv'))
        page.wait_for_function("document.querySelector('#toast').textContent.indexOf('35 new fills') >= 0")
        self.assertIn('62 already in the journal', page.inner_text('.sources'))
        self.assertIn('of 524 fills', page.inner_text('#view-fills'))

    def test_inside_a_frame(self):
        frame_page = os.path.join(self.tmp.name, 'frame.html')
        with open(frame_page, 'w', encoding='utf-8') as fh:
            fh.write('<!doctype html><title>Frame</title><iframe src="%s" style="width:1000px;height:800px"></iframe>' % URL)
        page = self.open(url='file://' + frame_page)
        frame = page.frames[1]
        frame.wait_for_selector('#review-sheet')
        self.assertIn('+$1,595.71', frame.inner_text('#headline'))
        frame.click('#tab-trades')
        self.assertTrue(frame.is_visible('#trade-ticket'))

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(width=390, height=844)
        for view in ['review', 'fills', 'trades', 'rules', 'how']:
            page.click('#tab-' + view)
            width = page.evaluate('document.documentElement.scrollWidth')
            self.assertLessEqual(width, 390, view)
        size = page.evaluate("getComputedStyle(document.querySelector('.axis-text') || document.body).fontSize")
        self.assertTrue(size.endswith('px'))

    def test_every_control_has_a_label(self):
        page = self.open()
        for view in ['review', 'fills', 'trades', 'rules', 'how']:
            page.click('#tab-' + view)
            if view == 'fills':
                page.click('.paste summary')
            self.assertEqual(page.evaluate(UNLABELLED), [], view)

    def test_copy_and_print_the_review(self):
        page = self.open()
        page.evaluate('window.print = function () { window.__printed = document.body.classList.contains("print-review"); }')
        page.click('[data-action="print-review"]')
        self.assertTrue(page.evaluate('window.__printed'))
        page.click('[data-action="copy-review"]')
        page.wait_for_function("document.querySelector('#toast').textContent.length > 0")


if __name__ == '__main__':
    unittest.main()
