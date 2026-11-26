"""Browser tests for app/index.html, driven by Playwright and headless Chromium.

Run from the repository root:  python -m unittest discover -s tests/ui -t .
Skipped when Playwright for Python is not installed.
"""

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

    def open(self, width=1280, height=900, url=APP):
        page = self.browser.new_page(viewport={'width': width, 'height': height})
        self.problems, self.requests = [], []
        page.on('console', lambda m: self.problems.append(m.text) if m.type in ('error', 'warning') else None)
        page.on('pageerror', lambda e: self.problems.append(str(e)))
        page.on('request', lambda r: self.requests.append(r.url)
                if not r.url.startswith(('file:', 'data:', 'about:')) else None)
        page.goto(url)
        self.addCleanup(page.close)
        return page

    def train(self, page):
        page.uncheck('#animate')
        page.click('#train-btn')
        page.wait_for_function("document.getElementById('train-status').textContent.indexOf('rounds.') > 0", timeout=60000)

    def assertClean(self):
        self.assertEqual(self.problems, [], 'console errors or warnings')
        self.assertEqual(self.requests, [], 'network requests')

    def test_learn_tab_trains_and_reports(self):
        page = self.open()
        self.assertIn('Nothing trained yet', page.inner_text('#learn-verdict'))
        self.train(page)
        kpis = page.inner_text('#learn-kpis')
        self.assertIn('PROFIT GAIN', kpis.upper())
        self.assertRegex(page.inner_text('#learn-verdict'), r'Prices settled')
        self.assertEqual(page.locator('#chart-learn path').count(), 2)   # one line per seller
        self.assertEqual(page.locator('#chart-heat rect').count(), 15 * 15 + 10)
        page.select_option('#heat-seller', '1')
        self.assertIn('seller B', page.inner_text('#heat-title'))
        self.assertClean()

    def test_presets_and_validation(self):
        page = self.open()
        page.select_option('#preset', 'three')
        self.assertTrue(page.is_visible('#type2'))
        page.select_option('#preset', 'textbook')
        self.assertFalse(page.is_visible('#type2'))
        page.select_option('#type0', 'nash')
        page.select_option('#type1', 'match')
        page.click('#train-btn')
        self.assertIn('at least one seller must learn', page.inner_text('#learn-errors'))
        self.assertEqual(page.input_value('#preset'), 'custom')
        self.assertClean()

    def test_threat_tab_shows_punishment(self):
        page = self.open()
        page.click('#tab-threat')
        self.assertTrue(page.is_visible('#threat-empty'))
        page.click('#threat-train')
        page.wait_for_selector('#threat-body:not([hidden])', timeout=60000)
        self.assertIn('Reward and punishment', page.inner_text('#threat-verdict'))
        self.assertEqual(page.locator('#br-table tr').count(), 3)
        page.select_option('#dev-seller', '1')
        page.fill('#horizon', '30')
        page.dispatch_event('#horizon', 'input')
        self.assertIn('30 days', page.inner_text('#horizon-out'))
        self.assertClean()

    def test_pilot_to_scale(self):
        page = self.open()
        page.click('#tab-pilot')
        self.assertTrue(page.is_visible('#pilot-empty'))
        page.fill('#pilot-runs', '2')
        page.dispatch_event('#pilot-runs', 'input')
        page.click('#pilot-run')
        page.wait_for_function("document.getElementById('pilot-status').textContent.indexOf('Finished') === 0", timeout=120000)
        self.assertEqual(page.locator('#pilot-table tr').count(), 5)
        self.assertIn('understated', page.inner_text('#pilot-verdict'))
        self.assertEqual(page.locator('#chart-pilot-runs circle').count(), 4)
        page.select_option('#pilot-rule', 'match')
        page.click('#pilot-run')
        page.click('#pilot-stop')
        self.assertIn('Stopped', page.inner_text('#pilot-status'))
        self.assertClean()

    def test_remedies_run_and_stop(self):
        page = self.open()
        page.click('#tab-remedies')
        boxes = page.locator('#rem-list input')
        for k in range(boxes.count()):
            if boxes.nth(k).get_attribute('value') not in ('baseline', 'own'):
                boxes.nth(k).uncheck()
        page.fill('#rem-runs', '2')
        page.dispatch_event('#rem-runs', 'input')
        page.click('#rem-run')
        page.wait_for_function("document.getElementById('rem-status').textContent.indexOf('Finished') === 0", timeout=120000)
        self.assertEqual(page.locator('#rem-table tr').count(), 3)
        self.assertIn('Biggest fall', page.inner_text('#rem-verdict'))
        page.select_option('#rem-metric', 'harm')
        self.assertGreater(page.locator('#chart-rem rect').count(), 1)
        # a long run can be stopped
        page.fill('#rem-runs', '30')
        page.dispatch_event('#rem-runs', 'input')
        page.click('#rem-run')
        page.click('#rem-stop')
        self.assertIn('Stopped', page.inner_text('#rem-status'))
        self.assertClean()

    def test_case_file_and_threshold(self):
        page = self.open()
        page.click('#tab-screens')
        page.fill('#cf-n', '10')
        page.dispatch_event('#cf-n', 'input')
        page.click('#cf-run')
        page.wait_for_function("document.getElementById('cf-status').textContent.indexOf('Built') === 0", timeout=120000)
        self.assertEqual(page.locator('#cf-table tr').count(), 11)
        self.assertEqual(page.locator('#chart-roc path').count(), 5)
        page.check('input[name="target"][value="highPrice"]', force=True)
        self.assertIn('50% or more', page.inner_text('#target-hint'))
        page.fill('#th-value', '0')
        page.dispatch_event('#th-value', 'input')
        kpis = page.inner_text('#th-kpis')
        self.assertIn('0\ninnocent and not flagged', kpis.replace('CLEARED\n', ''))
        self.assertClean()

    def test_your_prices_sample_and_errors(self):
        page = self.open()
        page.click('#tab-data')
        self.assertGreaterEqual(page.locator('#sample option').count(), 6)
        page.select_option('#sample', '0')
        self.assertTrue(page.is_visible('#data-verdict'))
        self.assertIn('Hidden truth for this sample', page.inner_text('#data-verdict'))
        page.fill('#csv', 'day,price_a,price_b\n1,2,2\n2,2,2')
        page.click('#data-run')
        self.assertIn('at least 30 days', page.inner_text('#data-errors'))
        page.fill('#csv', 'a;b\n' + '\n'.join('%d;x' % i for i in range(40)))
        page.click('#data-run')
        self.assertIn('Could not find two columns', page.inner_text('#data-errors'))
        rows = '\n'.join('%d,%.2f,%.2f' % (d, 1.9 - (0.2 if d % 11 == 4 else 0), 1.9 - (0.2 if d % 11 == 5 else 0))
                         for d in range(1, 121))
        page.fill('#csv', 'day,price_a,price_b\n' + rows)
        page.fill('#cost-a', '1')
        page.fill('#cost-b', '')
        page.click('#data-run')
        self.assertIn('both unit costs', page.inner_text('#data-errors'))
        page.fill('#cost-b', '1')
        page.click('#data-run')
        self.assertIn('more often than chance', page.inner_text('#data-verdict'))
        with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False) as f:
            f.write('day,price_a,price_b\n' + rows)
        self.addCleanup(os.unlink, f.name)
        page.set_input_files('#csv-file', f.name)
        page.wait_for_timeout(300)
        self.assertIn('120 days', page.inner_text('#data-sub'))
        self.assertClean()

    def test_keyboard_tabs(self):
        page = self.open()
        page.focus('#tab-learn')
        page.keyboard.press('ArrowRight')
        self.assertEqual(page.get_attribute('#tab-threat', 'aria-selected'), 'true')
        page.keyboard.press('End')
        self.assertEqual(page.get_attribute('#tab-about', 'aria-selected'), 'true')
        self.assertFalse(page.is_hidden('#panel-about'))
        page.keyboard.press('Home')
        self.assertEqual(page.get_attribute('#tab-learn', 'aria-selected'), 'true')
        self.assertClean()

    def test_every_control_has_a_label(self):
        page = self.open()
        unlabelled = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, textarea, button')).filter(el => {
            if (el.type === 'hidden') return false;
            if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
            if (el.tagName === 'BUTTON') return !el.textContent.trim();
            if (el.id && document.querySelector('label[for="' + el.id + '"]')) return false;
            return !el.closest('label');
        }).map(el => el.id || el.name || el.tagName)""")
        self.assertEqual(unlabelled, [])

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(width=390, height=844)
        self.train(page)
        for tab in ('learn', 'threat', 'pilot', 'remedies', 'screens', 'data', 'about'):
            page.click('#tab-' + tab)
            wide = page.evaluate('document.documentElement.scrollWidth')
            self.assertLessEqual(wide, 390, tab)
        self.assertClean()

    def test_works_inside_an_iframe(self):
        with tempfile.TemporaryDirectory() as d:
            host = pathlib.Path(d) / 'host.html'
            host.write_text('<!doctype html><title>host</title><iframe id="f" src="%s" style="width:900px;height:800px"'
                            ' sandbox="allow-scripts"></iframe>' % APP, encoding='utf-8')
            page = self.open(url=host.as_uri())
            frame = page.frame_locator('#f')
            frame.locator('#animate').uncheck()
            frame.locator('#train-btn').click()
            frame.locator('#train-status').filter(has_text='rounds.').wait_for(timeout=60000)
            frame.locator('#tab-threat').click()
            self.assertIn('punish', frame.locator('#threat-verdict').inner_text().lower())
            self.assertClean()


if __name__ == '__main__':
    unittest.main()
