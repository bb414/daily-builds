"""Browser tests for app/index.html, driven by Playwright and headless Chromium.

Run from the repository root:  python3 -m unittest discover -s tests/ui -t .
Skipped when Playwright for Python is not installed.
"""

import json
import os
import pathlib
import tempfile
import unittest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = (ROOT / 'app' / 'index.html').as_uri()
TABS = ['season', 'light', 'pilot', 'rotation', 'tradeoff', 'hidden', 'logbook', 'how']
READY = {'season': '#board svg', 'light': '#roc svg', 'pilot': '#pilot-power svg', 'rotation': '#rot-scatter svg',
         'tradeoff': '#trade-chart svg', 'hidden': '#hidden-map svg',
         'logbook': '#log-ratio svg', 'how': '.diagram'}


@unittest.skipIf(sync_playwright is None, 'Playwright for Python is not installed')
class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900, url=APP, init=None):
        ctx = self.browser.new_context(viewport={'width': width, 'height': height}, accept_downloads=True)
        page = ctx.new_page()
        self.errors, self.requests = [], []
        page.on('console', lambda m: self.errors.append(m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.on('request', lambda r: self.requests.append(r.url))
        if init:
            page.add_init_script(init)
        page.goto(url)
        page.wait_for_selector('#board svg')
        self.addCleanup(ctx.close)
        return page

    def tab(self, page, name):
        page.click('#tab-' + name)
        page.wait_for_selector(READY[name], timeout=60000)

    def outside_requests(self):
        return [u for u in self.requests if not u.startswith(('file:', 'data:', 'blob:'))]

    def test_opens_on_a_real_result_with_no_errors_or_network(self):
        page = self.open()
        tiles = page.locator('#season-out .tile .t-value').all_inner_texts()
        self.assertEqual(4, len(tiles))
        self.assertTrue(tiles[0].strip().isdigit())
        self.assertNotIn('n/a', ' '.join(tiles))
        self.assertEqual(36, page.locator('#board .rowhit').count())
        self.assertIn('Physio', page.text_content('.note-card'))
        self.assertEqual(24, page.locator('#fixtures li').count())
        self.assertEqual([], self.errors)
        self.assertEqual([], self.outside_requests())

    def test_every_page_renders_without_errors(self):
        page = self.open()
        for name in TABS:
            self.tab(page, name)
            self.assertEqual('true', page.get_attribute('#tab-' + name, 'aria-selected'))
            self.assertFalse(page.is_hidden('#view-' + name))
        self.assertEqual(5, page.locator('#light-out tbody tr').count())
        self.assertEqual(7, page.locator('#rotation-out tbody tr').count())
        self.assertEqual(3, page.locator('#log-results .sheet-table').first.locator('tbody tr').count())
        self.assertEqual([], self.errors)
        self.assertEqual([], self.outside_requests())

    def test_choosing_a_player_and_changing_policy_update_the_season(self):
        page = self.open()
        page.click('#board .rowhit[data-p="10"]')
        name = page.text_content('#player-card .pname')
        self.assertIn(name, page.inner_text('#player-pick option:checked'))
        page.select_option('#player-pick', '3')
        self.assertNotEqual(name, page.text_content('#player-card .pname'))
        page.click('label[for="pol-none"]')
        page.wait_for_function("document.querySelector('.note-card').innerText.indexOf('Nobody acted') >= 0")
        page.click('label[for="pol-rotate"]')
        page.wait_for_function("document.querySelector('.note-card').innerText.indexOf('ignores the light') >= 0")
        before = page.inner_text('#season-out .tile .t-value')
        page.click('#next-season')
        page.wait_for_function("document.getElementById('season-val').textContent === '7'")
        self.assertEqual([], self.errors)
        self.assertTrue(before)

    def test_the_inquest_lists_injuries_and_opens_player_files(self):
        page = self.open()
        page.wait_for_selector('#inquest-out table')
        soft = page.locator('#inquest-out tbody tr').count()
        self.assertGreater(soft, 3)
        page.click('label[for="inq-all"]')
        page.wait_for_function('document.querySelectorAll("#inquest-out tbody tr").length > %d' % soft)
        self.assertIn('acting on the light', page.text_content('#inquest-out .note-card'))
        button = page.locator('#inquest-out button.linkish').nth(2)
        name = button.text_content()
        button.click()
        page.wait_for_function('document.querySelector("#player-card .pname").textContent === %r' % name)
        self.assertEqual([], self.errors)

    def test_the_trade_off_responds_to_the_worth_of_a_point(self):
        page = self.open()
        self.tab(page, 'tradeoff')
        rows = page.locator('#trade-body tbody tr').count()
        self.assertEqual(19, rows)
        page.fill('#point-value', '0')
        page.dispatch_event('#point-value', 'input')
        page.wait_for_function("document.querySelector('#trade-body .tile .t-value').textContent.indexOf('30%') >= 0")
        page.fill('#point-value', '50')
        page.dispatch_event('#point-value', 'input')
        page.wait_for_function("document.querySelector('#trade-body .tile .t-value').textContent.indexOf('readiness') >= 0")
        self.assertIn('50 player-days', page.text_content('#point-value-val'))
        self.assertEqual([], self.errors)

    def test_the_hidden_truth_page_switches_measure(self):
        page = self.open()
        self.tab(page, 'hidden')
        self.assertEqual(2 * 7, page.locator('#tornado rect').count())
        page.click('label[for="hm-auc"]')
        page.wait_for_function("document.querySelector('#tornado .legend').textContent.indexOf('silent seasons') >= 0")
        self.assertEqual(15, page.locator('#hidden-map rect').count())
        self.assertEqual([], self.errors)

    def test_ratio_and_budget_controls_follow_the_light(self):
        page = self.open()
        self.assertTrue(page.is_hidden('#threshold-field'))
        page.select_option('#flag', 'ewma')
        self.assertFalse(page.is_hidden('#threshold-field'))
        self.assertTrue(page.is_hidden('#budget-field'))
        page.fill('#threshold', '1.3')
        page.dispatch_event('#threshold', 'input')
        page.wait_for_function("document.getElementById('threshold-val').textContent === '1.3'")
        page.wait_for_function("document.querySelector('.note-card .from').textContent.indexOf('EWMA') >= 0")

    def test_pilot_and_rotation_options_rerun(self):
        page = self.open()
        self.tab(page, 'pilot')
        page.click('label[for="pairs-20"]')
        page.wait_for_selector('#pilot-power svg')
        self.assertIn('20', page.inner_text('#pilot-out'))
        self.tab(page, 'rotation')
        page.click('label[for="rs-15"]')
        page.wait_for_selector('#rot-final svg')
        self.assertTrue(page.is_checked('#rs-15'))
        self.assertEqual([], self.errors)

    def test_share_link_and_settings_file_round_trip(self):
        page = self.open()
        page.select_option('#flag', 'ewma')
        page.click('label[for="pol-modify"]')
        page.click('label[for="pre-steep"]')
        page.click('#copy-link')
        page.wait_for_function("location.hash.indexOf('#s=') === 0")
        link = page.evaluate('location.href')
        other = self.open(url=link)
        self.assertEqual('ewma', other.eval_on_selector('#flag', 'e => e.value'))
        self.assertTrue(other.is_checked('#pol-modify'))
        self.assertTrue(other.is_checked('#pre-steep'))
        with page.expect_download() as dl:
            page.click('#save-settings')
        path = dl.value.path()
        data = json.loads(pathlib.Path(path).read_text())
        self.assertEqual('load-bearing', data['app'])
        self.assertEqual('modify', data['settings']['policy'])
        fresh = self.open()
        with fresh.expect_file_chooser() as fc:
            fresh.click('#load-settings')
        fc.value.set_files(path)
        fresh.wait_for_function("document.getElementById('flag').value === 'ewma'")
        self.assertTrue(fresh.is_checked('#pol-modify'))

    def test_a_broken_link_falls_back_to_the_defaults(self):
        page = self.open(url=APP + '#s=not-really-a-link')
        self.assertEqual('model', page.eval_on_selector('#flag', 'e => e.value'))
        self.assertEqual([], self.errors)

    def test_logbook_reads_pasted_rows_and_reports_bad_input(self):
        page = self.open()
        self.tab(page, 'logbook')
        page.click('#logbook-out details summary')
        page.fill('#paste', 'when,who\nyesterday,nobody\n')
        page.click('#read-paste')
        page.wait_for_selector('#log-results .error')
        self.assertIn('date column', page.inner_text('#log-results .error'))
        rows = ['date,player,minutes,rpe,injury']
        for d in range(1, 61):
            day = '2026-%02d-%02d' % (9 + (d - 1) // 30, (d - 1) % 30 + 1)
            for p in ('A. One', 'B. Two', 'C. Three'):
                rows.append('%s,%s,%d,%d,%s' % (day, p, 60 + (d * 7) % 30, 5 + d % 3, 'non-contact' if (d, p) in ((40, 'A. One'), (50, 'B. Two'), (55, 'C. Three')) else ''))
        page.fill('#paste', '\n'.join(rows))
        page.click('#read-paste')
        page.wait_for_selector('#log-ratio svg')
        self.assertIn('pasted rows', page.inner_text('#log-name'))
        self.assertEqual('3', page.inner_text('#log-results .tile .t-value').strip())
        page.wait_for_selector('#spike-out')
        page.select_option('#log-only', 'all')
        page.wait_for_selector('#log-ratio svg')
        with page.expect_download() as dl:
            page.click('#dl-flags')
        self.assertTrue(dl.value.suggested_filename.endswith('.csv'))
        self.assertEqual([], self.errors)

    def test_logbook_calibration_card(self):
        page = self.open()
        self.tab(page, 'logbook')
        page.wait_for_selector('#spike-chart svg', timeout=60000)
        self.assertIn('the truth is known', page.text_content('#spike-out .note-card'))
        self.assertEqual(4, page.locator('#spike-out .tile').count())

    def test_logbook_file_upload_and_sample_download(self):
        page = self.open()
        self.tab(page, 'logbook')
        with page.expect_download() as dl:
            page.click('#dl-sample')
        sample = pathlib.Path(dl.value.path()).read_text()
        self.assertEqual((ROOT / 'data' / 'club_logbook.csv').read_text(), sample)
        with tempfile.TemporaryDirectory() as tmp:
            f = os.path.join(tmp, 'mine.csv')
            pathlib.Path(f).write_text('\n'.join(sample.split('\n')[:3000]) + '\n')
            page.set_input_files('#csv-file', f)
            page.wait_for_function("document.getElementById('log-name').textContent === 'mine.csv'")
            page.wait_for_selector('#log-ratio svg')

    def test_keyboard_moves_between_pages_and_controls_are_labelled(self):
        page = self.open()
        page.focus('#tab-season')
        page.keyboard.press('ArrowRight')
        page.wait_for_selector('#roc svg', timeout=60000)
        self.assertEqual('true', page.get_attribute('#tab-light', 'aria-selected'))
        page.keyboard.press('End')
        self.assertEqual('true', page.get_attribute('#tab-how', 'aria-selected'))
        unlabelled = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, textarea, button'))
          .filter(el => el.type !== 'hidden' && !el.hidden && el.offsetParent !== null || el.closest('.tickets, .policy-list'))
          .filter(el => {
            if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
            if (el.tagName === 'BUTTON') return !el.textContent.trim();
            if (el.id && document.querySelector('label[for="' + el.id + '"]')) return false;
            return !el.closest('label');
          }).map(el => el.id || el.name || el.tagName)""")
        self.assertEqual([], unlabelled)

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(width=390, height=844)
        for name in TABS:
            self.tab(page, name)
            width = page.evaluate('document.documentElement.scrollWidth')
            self.assertLessEqual(width, 391, name)
        small = page.evaluate("""() => Array.from(document.querySelectorAll('.chart text'))
          .filter(t => t.getBoundingClientRect().width > 0)
          .map(t => parseFloat(getComputedStyle(t).fontSize)).filter(s => s < 11).length""")
        self.assertEqual(0, small)
        self.assertEqual([], self.errors)

    def test_works_inside_a_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            host = pathlib.Path(tmp) / 'host.html'
            host.write_text('<!doctype html><title>host</title><iframe id="f" src="%s" width="900" height="700"></iframe>' % APP)
            ctx = self.browser.new_context(viewport={'width': 1000, 'height': 800})
            self.addCleanup(ctx.close)
            page = ctx.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('console', lambda m: errors.append(m.text) if m.type == 'error' else None)
            page.goto(host.as_uri())
            frame = page.frame_locator('#f')
            frame.locator('#board svg').wait_for()
            frame.locator('#tab-pilot').click()
            frame.locator('#pilot-power svg').wait_for(timeout=60000)
            self.assertEqual([], errors)

    def test_works_without_web_workers(self):
        page = self.open(init='window.Worker = undefined;')
        self.tab(page, 'light')
        self.assertEqual(5, page.locator('#light-out tbody tr').count())
        self.assertEqual([], self.errors)


if __name__ == '__main__':
    unittest.main()
