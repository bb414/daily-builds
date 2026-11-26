"""Browser tests for app/index.html, driven by Playwright and headless Chromium.

Run from the repository root:  python -m unittest discover -s tests/ui -t .
Skipped when Playwright for Python is not installed.
"""

import base64
import json
import os
import pathlib
import random
import tempfile
import unittest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = (ROOT / 'app' / 'index.html').as_uri()


def link(state):
    """A share link for the app with these settings, as the Copy a link button makes them."""
    raw = json.dumps(dict({'app': 'quiet-cartel', 'v': 1}, **state)).encode('utf-8')
    return APP + '#s=' + base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')


def unlink(url):
    """The settings inside a share link."""
    code = url.split('#s=', 1)[1]
    return json.loads(base64.urlsafe_b64decode(code + '=' * (-len(code) % 4)).decode('utf-8'))


def csv_market(mid, days=40, cuts=(), follow=True, quote=False):
    """Rows for one market: both sellers at 2.00, seller A cutting to 1.80 for a day on each day in cuts and,
    when follow is set, seller B cutting the day after."""
    out = []
    for d in range(1, days + 1):
        a = 1.8 if d in cuts else 2.0
        b = 1.8 if follow and d - 1 in cuts else 2.0
        cell = '"%s"' % mid.replace('"', '""') if quote else mid
        out.append('%s,%d,%.2f,%.2f' % (cell, d, a, b))
    return out


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

    def test_robustness_tornado_and_map(self):
        page = self.open()
        page.click('#tab-robust')
        self.assertTrue(page.is_visible('#rb-empty'))
        page.fill('#rb-runs', '1')
        page.dispatch_event('#rb-runs', 'input')
        page.click('#rb-tornado')
        page.wait_for_function("document.getElementById('rb-status').textContent.indexOf('Finished') === 0", timeout=180000)
        self.assertEqual(page.locator('#chart-tornado circle').count(), 14)
        page.select_option('#rb-metric', 'punished')
        self.assertIn('assumptions', page.inner_text('#rb-verdict'))
        page.click('#rb-map')
        page.wait_for_function("document.getElementById('rb-status').textContent.indexOf('Finished 25') === 0", timeout=180000)
        self.assertEqual(page.locator('#chart-map rect').count(), 25)
        self.assertIn('combinations', page.inner_text('#rb-verdict'))
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

    def test_share_link_and_settings_file(self):
        page = self.open()
        page.select_option('#preset', 'loyal')
        page.select_option('#memory', 'own')
        page.click('#tab-pilot')
        page.select_option('#pilot-rule', 'undercut')
        page.click('#share-btn')
        link = page.input_value('#share-link')
        self.assertIn('#s=', link)
        other = self.open(url=link)
        self.assertEqual(other.input_value('#memory'), 'own')
        self.assertEqual(other.input_value('#mu'), '0.5')
        self.assertEqual(other.input_value('#pilot-rule'), 'undercut')
        self.assertEqual(other.get_attribute('#tab-pilot', 'aria-selected'), 'true')
        broken = self.open(url=APP + '#s=not-really-settings')
        self.assertIn('could not be read', broken.inner_text('#state-notice'))
        with page.expect_download() as dl:
            page.click('#save-btn')
        path = dl.value.path()
        with tempfile.TemporaryDirectory() as d:
            bad = pathlib.Path(d) / 'bad.json'
            bad.write_text('{"app": "quiet-cartel", "learn": {"mu": 7}, "remedies": {"runs": 99}}', encoding='utf-8')
            fresh = self.open()
            fresh.set_input_files('#load-file', str(bad))
            fresh.wait_for_timeout(300)
            notice = fresh.inner_text('#state-notice')
            self.assertIn('mu must be between', notice)
            self.assertIn('Remedy runs', notice)
            fresh.set_input_files('#load-file', path)
            fresh.wait_for_timeout(300)
            self.assertEqual(fresh.input_value('#memory'), 'own')
        self.assertClean()

    def test_many_markets_and_downloads(self):
        lines = (ROOT / 'data' / 'markets.csv').read_text(encoding='utf-8').splitlines()
        keep = [lines[0]] + [l for l in lines[1:] if l.split(',')[0] in ('1', '4', '11')]
        page = self.open()
        page.click('#tab-data')
        page.fill('#csv', '\n'.join(keep))
        page.click('#data-run')
        page.wait_for_function("document.getElementById('data-status').textContent.indexOf('Screened 3') === 0", timeout=60000)
        self.assertEqual(page.locator('#panel-table tr').count(), 4)
        self.assertIn('market', page.inner_text('#data-sub'))
        page.click('#panel-table button[data-market="11"]')
        self.assertIn('market 11', page.inner_text('#data-sub'))
        self.assertIn('margin', page.inner_text('#panel-table').lower())
        with page.expect_download() as dl:
            page.click('#panel-csv')
        text = pathlib.Path(dl.value.path()).read_text(encoding='utf-8')
        self.assertTrue(text.startswith('market,days,unprovoked_cuts'))
        self.assertEqual(len(text.strip().splitlines()), 4)
        page.click('#tab-remedies')
        boxes = page.locator('#rem-list input')
        for k in range(boxes.count()):
            if boxes.nth(k).get_attribute('value') != 'baseline':
                boxes.nth(k).uncheck()
        page.fill('#rem-runs', '2')
        page.dispatch_event('#rem-runs', 'input')
        page.click('#rem-run')
        page.wait_for_function("document.getElementById('rem-status').textContent.indexOf('Finished') === 0", timeout=60000)
        with page.expect_download() as dl:
            page.click('#rem-csv')
        self.assertEqual(len(pathlib.Path(dl.value.path()).read_text(encoding='utf-8').strip().splitlines()), 3)
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
        for tab in ('learn', 'threat', 'pilot', 'remedies', 'robust', 'screens', 'data', 'about'):
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

    # ---------------------------------------------------------------- regression tests from the interface audit

    def test_hidden_blocks_stay_hidden(self):
        # .layout, .kpis and .grid2 set their own display, which used to override the hidden attribute: the threat
        # tab showed its empty controls before training, and the screens tab two empty cards before a case file.
        page = self.open()
        for tab in ('learn', 'threat', 'pilot', 'remedies', 'robust', 'screens', 'data', 'about'):
            page.click('#tab-' + tab)
            shown = page.evaluate("""() => Array.from(document.querySelectorAll('[hidden]'))
                .filter(e => getComputedStyle(e).display !== 'none').map(e => e.id || e.className)""")
            self.assertEqual(shown, [], tab)
        page.click('#tab-threat')
        self.assertFalse(page.is_visible('#threat-body'))
        page.click('#tab-screens')
        self.assertFalse(page.is_visible('#cf-top'))
        self.assertClean()

    def test_textbook_trains_with_the_exact_default_settings(self):
        # The discount-speed slider cannot show 4e-6 exactly; the Learn tab used to train at 3.95e-6 instead,
        # so its runs differed from the Python companion's (98% profit gain instead of 79% for seed 1).
        page = self.open()
        page.click('#share-btn')
        self.assertEqual(unlink(page.input_value('#share-link'))['learn']['beta'], 4e-06)
        self.train(page)
        self.assertIn('the other hits back', page.inner_text('#learn-verdict'))
        page.click('#tab-threat')
        kpis = page.inner_text('#threat-kpis')
        self.assertIn('£23.65', kpis)   # FINDINGS.md: with seed 1, A gains £23.65 per 1,000 shoppers on the day
        self.assertIn('£165.15', kpis)  # and loses £165.15 afterwards
        self.assertClean()

    def test_settled_table_shows_average_day_profits_with_busy_and_quiet_days(self):
        # With demand noise the table used to show the quietest day's profits next to average-day benchmarks.
        page = self.open(url=link({'learn': {'demandNoise': 0.2}}))
        self.train(page)
        expected = page.evaluate("""() => {
            var tr = QC.train(Object.assign(QC.defaultConfig(), { demandNoise: 0.2 })), s = QC.summarise(tr), mk = tr.market;
            var a = QC.decodeJoint(s.cycle[0], 2, mk.m);
            return (QC.profitsAt([mk.grids[0][a[0]], mk.grids[1][a[1]]], mk.quality, mk.cost, mk.outside, mk.mu)[0] * 1000).toFixed(2);
        }""")
        first = page.locator('#cycle-box tr').nth(1).locator('td')
        self.assertEqual(first.nth(3).inner_text(), '£' + expected)   # Day, Price A, Price B, Profit A
        self.assertIn('on an average day', page.inner_text('#cycle-box'))
        self.assertClean()

    def test_rule_seller_wording(self):
        page = self.open()
        page.select_option('#preset', 'matcher')
        self.train(page)
        self.assertIn('Only the learning seller adapted; the other followed a fixed rule.', page.inner_text('#learn-verdict'))
        self.assertClean()

    def test_three_sellers_without_memory_read_correctly(self):
        # "No rival did not lower its price" used to appear with three sellers.
        page = self.open(url=link({'learn': {'nFirms': 3, 'memory': 'none'}}))
        self.train(page)
        page.click('#tab-threat')
        verdict = page.inner_text('#threat-verdict')
        self.assertIn('No rival lowered its price in response', verdict)
        self.assertNotIn('did not', verdict)
        self.assertEqual(page.locator('#br-table tr').count(), 4)
        self.assertClean()

    def test_best_reply_caption_agrees_with_the_table(self):
        # Own price only, seed 1: play has settled just short of a best reply (gain 0.4%); the caption used to call it
        # an exact equilibrium while the table said "no".
        page = self.open(url=link({'learn': {'memory': 'own'}}))
        self.train(page)
        page.click('#tab-threat')
        cells = [c.strip() for line in page.inner_text('#br-table').split('\n')[1:] for c in line.split('\t')]
        self.assertIn('no', cells)
        caption = page.inner_text('#br-caption')
        self.assertIn('very close to an equilibrium', caption)
        self.assertNotIn('already playing its best reply', caption)
        self.assertClean()

    def test_a_later_answer_is_not_called_no_threat(self):
        # Close substitutes, seed 5: the rival does not answer the next day but cuts later, and the cut loses money.
        page = self.open(url=link({'learn': {'mu': 0.1, 'seed': 5}}))
        self.train(page)
        page.click('#tab-threat')
        verdict = page.inner_text('#threat-verdict')
        self.assertIn('Late reaction', verdict)
        self.assertNotIn('Nobody hits back', verdict)
        self.assertClean()

    def test_a_best_price_rise_is_not_called_a_cut(self):
        # Impatient algorithms, seed 9: seller A's best one-day price is above its settled price.
        page = self.open(url=link({'learn': {'delta': 0.5, 'seed': 9}}))
        self.train(page)
        page.click('#tab-threat')
        self.assertIn('a rise to', page.inner_text('#dev-price option[value="best"]'))
        verdict = page.inner_text('#threat-verdict')
        self.assertIn('raised its price from', verdict)
        self.assertNotIn('cut from', verdict)
        self.assertIn('NET EFFECT OF THE RISE', page.inner_text('#threat-kpis').upper())
        self.assertClean()

    def test_old_results_are_cleared_while_training_again(self):
        page = self.open()
        self.train(page)
        page.check('#animate')
        page.click('#train-btn')
        self.assertIn('Training', page.inner_text('#learn-verdict'))
        self.assertNotIn('%', page.inner_text('#learn-kpis'))
        page.click('#tab-threat')
        self.assertIn('under way', page.inner_text('#threat-empty'))
        self.assertFalse(page.is_visible('#threat-train'))   # it would have cancelled the run under way
        page.wait_for_function("document.getElementById('train-status').textContent.indexOf('rounds.') > 0", timeout=60000)
        self.assertTrue(page.is_visible('#threat-body'))
        self.assertClean()

    def test_big_market_waits_for_the_slow_best_reply_check(self):
        # Three sellers, 21 prices and patience 0.99: the exact check used to freeze the page for about six seconds
        # as soon as the threat tab opened.
        page = self.open(width=390, height=844, url=link({'learn': {'nFirms': 3, 'nPrices': 21, 'delta': 0.99}}))
        self.train(page)
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        ms = page.evaluate("() => { var t0 = performance.now(); document.getElementById('tab-threat').click(); return performance.now() - t0; }")
        self.assertLess(ms, 1000)
        self.assertIn('waits until you ask', page.inner_text('#br-caption'))
        self.assertIn('Not checked yet', page.inner_text('#br-table'))
        self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'), 390)
        page.click('#br-run')
        page.wait_for_selector('#br-actions', state='hidden', timeout=120000)
        self.assertEqual(page.locator('#br-table tr').count(), 4)
        self.assertNotIn('Not checked yet', page.inner_text('#br-table'))
        self.assertClean()

    def test_pilot_legend_and_a_fair_pilot(self):
        # Myopic algorithms with near-identical products: the pilot predicts the result at scale (both 0%).
        page = self.open(url=link({'learn': {'delta': 0, 'mu': 0.05}, 'pilot': {'rule': 'nash', 'after': 500000, 'runs': 1}, 'tab': 'pilot'}))
        page.click('#pilot-run')
        page.wait_for_function("document.getElementById('pilot-status').textContent.indexOf('Finished') === 0", timeout=120000)
        verdict = page.inner_text('#pilot-verdict')
        self.assertIn('fair guide', verdict)
        self.assertNotIn('measured the rival', verdict)
        self.assertNotIn('comes from both sellers competing less hard', verdict)
        self.assertIn('PROFIT CHANGE', page.inner_text('#pilot-table').upper())
        # the legend describes the rule that ran, not whatever is chosen afterwards
        page.select_option('#pilot-rule', 'undercut')
        page.click('#tab-learn')
        page.click('#tab-pilot')
        self.assertIn('keeps its old competitive price', page.inner_text('#legend-pilot'))
        self.assertClean()

    def test_a_remedy_that_raises_prices_is_not_called_a_fall(self):
        page = self.open()
        page.click('#tab-remedies')
        boxes = page.locator('#rem-list input')
        for k in range(boxes.count()):
            if boxes.nth(k).get_attribute('value') not in ('baseline', 'matcher'):
                boxes.nth(k).uncheck()
        page.fill('#rem-runs', '2')
        page.dispatch_event('#rem-runs', 'input')
        page.click('#rem-run')
        page.wait_for_function("document.getElementById('rem-status').textContent.indexOf('Finished') === 0", timeout=120000)
        verdict = page.inner_text('#rem-verdict')
        self.assertIn('None of these options lowers the profit gain', verdict)
        self.assertNotIn('Biggest fall', verdict)
        self.assertClean()

    def test_a_remedy_the_learn_tab_already_uses(self):
        # With the Learn tab already banning rivals' prices, that option is the baseline itself.
        page = self.open(url=link({'learn': {'memory': 'own'}, 'remedies': {'runs': 2, 'options': ['baseline', 'own']}, 'tab': 'remedies'}))
        page.click('#rem-run')
        page.wait_for_function("document.getElementById('rem-status').textContent.indexOf('Finished') === 0", timeout=120000)
        self.assertIn('same market as the baseline', page.inner_text('#rem-verdict'))
        table = page.inner_text('#rem-table')
        self.assertIn('0 pts', table)
        self.assertNotIn('+0 pts', table)   # no sign on a change of nothing
        self.assertClean()

    def test_map_without_memory_does_not_claim_a_threat(self):
        page = self.open(url=link({'learn': {'memory': 'none'}, 'robustness': {'cell': 1}, 'tab': 'robust'}))
        page.click('#rb-map')
        page.wait_for_function("document.getElementById('rb-status').textContent.indexOf('Finished 25') === 0", timeout=180000)
        verdict = page.inner_text('#rb-verdict')
        self.assertIn('No square shows a threat', verdict)
        self.assertNotIn('makes the threat pay', verdict)
        self.assertClean()

    def test_case_file_seed_check_and_a_file_where_every_market_is_a_case(self):
        page = self.open()
        page.click('#tab-screens')
        page.fill('#cf-seed', '-3')
        page.click('#cf-run')
        self.assertIn('whole number', page.inner_text('#cf-status'))
        self.assertFalse(page.is_disabled('#cf-run'))
        # seed 27 with ten markets: all ten have high prices, so no screen can be scored on that definition
        page.fill('#cf-n', '10')
        page.dispatch_event('#cf-n', 'input')
        page.fill('#cf-seed', '27')
        page.check('input[name="target"][value="highPrice"]', force=True)
        page.click('#cf-run')
        page.wait_for_function("document.getElementById('cf-status').textContent.indexOf('Built') === 0", timeout=120000)
        verdict = page.inner_text('#cf-verdict')
        self.assertIn('cannot be scored', verdict)
        self.assertIn('Every market', verdict)
        self.assertNotIn('n/a', verdict)
        page.click('#tab-data')
        page.select_option('#sample', '0')
        self.assertIn('AT LEAST AS HIGH AS', page.inner_text('#data-compare').upper())
        self.assertClean()

    def test_analyse_button_comes_back_after_switching_to_a_sample(self):
        page = self.open()
        page.click('#tab-data')
        page.evaluate("(t) => { var box = document.getElementById('csv'); box.value = t; box.dispatchEvent(new Event('input')); }",
                      (ROOT / 'data' / 'markets.csv').read_text(encoding='utf-8'))
        # pick a sample while the 40 markets are still being screened (before the first step has even run)
        was_disabled = page.evaluate("""() => {
            document.getElementById('data-run').click();
            var busy = document.getElementById('data-run').disabled, s = document.getElementById('sample');
            s.value = '0'; s.dispatchEvent(new Event('change'));
            return busy; }""")
        self.assertTrue(was_disabled)
        self.assertFalse(page.is_disabled('#data-run'))
        self.assertEqual(page.inner_text('#data-status'), '')
        self.assertIn('Hidden truth', page.inner_text('#data-verdict'))
        page.wait_for_timeout(500)
        self.assertFalse(page.is_disabled('#data-run'))
        self.assertFalse(page.is_visible('#data-panel-card'))
        self.assertClean()

    def test_csv_edge_cases_and_hostile_market_ids(self):
        page = self.open()
        page.click('#tab-data')
        cuts = (5, 15, 25)
        hostile = '<img src=x onerror="window.pwned=1">'
        rows = (csv_market('__proto__', cuts=cuts) + csv_market('constructor', cuts=cuts) + csv_market('=1+2', cuts=cuts)
                + csv_market(hostile, cuts=cuts, quote=True) + csv_market('North, East', cuts=cuts, quote=True))
        # a byte order mark, as Excel writes, must not hide the market column
        page.fill('#csv', chr(0xFEFF) + 'market,day,price_a,price_b\n' + '\n'.join(rows))
        page.click('#data-run')
        page.wait_for_function("document.getElementById('data-status').textContent.indexOf('Screened 5') === 0", timeout=60000)
        table = page.inner_text('#panel-table')
        for mid in ('__proto__', 'constructor', '=1+2', hostile, 'North, East'):
            self.assertIn(mid, table)
        with page.expect_download() as dl:
            page.click('#panel-csv')
        lines = pathlib.Path(dl.value.path()).read_text(encoding='utf-8').splitlines()
        self.assertTrue(any(l.startswith("'=1+2,") for l in lines))   # a spreadsheet will not run it as a formula
        self.assertTrue(any(l.startswith('"North, East",') for l in lines))
        self.assertEqual(page.locator('#panel-table img').count(), 0)
        self.assertIsNone(page.evaluate('window.pwned'))
        page.click('#panel-table button[aria-label="View market constructor"]')
        self.assertIn('market constructor, 40 days', page.inner_text('#data-sub'))

        def errors_for(text):
            page.fill('#csv', text)
            page.click('#data-run')
            return page.inner_text('#data-errors')

        days = ['%d,2.00,2.00' % d for d in range(1, 41)]
        self.assertIn('Line 6 has a price', errors_for('day,price_a,price_b\n' + '\n'.join(days[:4] + ['5,Infinity,2.00'] + days[5:])))
        self.assertFalse(page.is_visible('#data-verdict'))   # results for earlier prices are not left on show
        self.assertIn('Line 3 has a price', errors_for('day,price_a,price_b\n1,2,2\n2,0x10,2\n' + '\n'.join(days[2:])))
        self.assertIn('never closed', errors_for('market,day,price_a,price_b\n"open,1,2,2\n' + '\n'.join('m,' + r for r in days)))
        self.assertIn('unit cost', errors_for('day,price_a,price_b,cost_a,cost_b\n' + '\n'.join(r + ',-1,1' for r in days)))
        self.assertIn('same day', errors_for('day,price_a,price_b\n' + '\n'.join(days + ['40,2.00,2.00'])))
        # semicolons with decimal commas
        self.assertEqual(errors_for('day;price_a;price_b\n' + '\n'.join('%d;2,00;2,10' % d for d in range(1, 41))), '')
        self.assertIn('40 days', page.inner_text('#data-sub'))
        # dates newest first are put in order: A cuts on 10 January and B answers on the 11th, staying low to the 13th
        lines = []
        for d in range(40, 0, -1):
            lines.append('2026-%02d-%02d,%.2f,%.2f' % (1 + (d - 1) // 31, 1 + (d - 1) % 31, 1.8 if d == 10 else 2.0, 1.8 if d in (11, 12, 13) else 2.0))
        self.assertEqual(errors_for('date,price_a,price_b\n' + '\n'.join(lines)), '')
        self.assertIn('100%', page.locator('#data-kpis .kpi').nth(1).inner_text())
        self.assertClean()

    def test_unit_cost_boxes(self):
        page = self.open()
        page.click('#tab-data')
        page.select_option('#sample', '0')
        self.assertEqual(page.input_value('#cost-a'), '1')
        # costs filled in by a sample go when other prices replace it
        page.fill('#csv', 'day,price_a,price_b\n' + '\n'.join('%d,2.00,2.00' % d for d in range(1, 41)))
        self.assertEqual(page.input_value('#cost-a'), '')
        page.click('#cost-a')
        page.keyboard.type('1e')               # not a number, though the box reports an empty value
        page.fill('#cost-b', '1')
        page.click('#data-run')
        self.assertIn('A unit cost is not a number', page.inner_text('#data-errors'))
        page.click('#tab-learn')
        page.click('#learn-form summary')
        page.click('#seed')
        page.keyboard.press('Control+A')
        page.keyboard.type('1e')
        page.click('#train-btn')
        self.assertIn('seed must be a whole number', page.inner_text('#learn-errors'))
        self.assertFalse(page.is_disabled('#train-btn'))
        self.assertClean()

    def test_screened_market_verdict_agrees_with_its_flag(self):
        # One market where B always answers A's cuts, screened with 59 markets that never move: on its own p is
        # tiny, but q (allowing for 60 markets) is above 0.10, so the market is not flagged and the verdict must agree.
        rng = random.Random(7)
        cuts, d = [], 4
        while d < 115:
            cuts.append(d)
            d += rng.randint(4, 12)
        rows = csv_market('strong', days=120, cuts=set(cuts))
        for k in range(59):
            rows += csv_market('flat%d' % k, days=30)
        page = self.open()
        page.click('#tab-data')
        page.fill('#csv', 'market,day,price_a,price_b\n' + '\n'.join(rows))
        page.click('#data-run')
        page.wait_for_function("document.getElementById('data-status').textContent.indexOf('Screened 60') === 0", timeout=60000)
        self.assertIn('0 of 60 flagged', page.inner_text('#panel-sub'))
        self.assertIn('market strong', page.inner_text('#data-sub'))
        verdict = page.inner_text('#data-verdict')
        self.assertIn('not flagged', verdict)
        self.assertNotIn('more often than chance allows', verdict)
        self.assertClean()

    def test_hostile_share_link_and_settings_file(self):
        st = {'tab': 'screens',
              'learn': {'mu': '<b>x</b>', 'firmTypes': ['<script>'], 'xi': 0.3, 'delta': 0.333},
              'pilot': {'rule': '<img src=x onerror="window.pwned=1">'},
              'caseFile': {'target': '"]<img src=x onerror="window.pwned=1">', 'seed': 'abc'}}
        page = self.open(url=link(st))
        notice = page.inner_text('#state-notice')
        for words in ('mu must be a number', 'firmTypes[0]', 'xi cannot be set', 'delta was rounded to 0.33',
                      'unknown rule', 'unknown definition', 'Case file seed'):
            self.assertIn(words, notice)
        self.assertEqual(page.locator('#state-notice img, #state-notice b, #state-notice script').count(), 0)
        self.assertIsNone(page.evaluate('window.pwned'))
        self.assertEqual(page.get_attribute('#tab-screens', 'aria-selected'), 'true')
        page.click('#tab-learn')
        self.assertIn('Nothing trained yet', page.inner_text('#learn-verdict'))   # the page finished starting up
        # a new link in the same tab is read too
        page.evaluate('(h) => { location.hash = h; }', link({'learn': {'memory': 'own'}}).split('#', 1)[1])
        page.wait_for_function("document.getElementById('memory').value === 'own'", timeout=5000)
        # a broken settings file can be fixed and chosen again
        with tempfile.TemporaryDirectory() as d:
            bad = pathlib.Path(d) / 'settings.json'
            bad.write_text('{not json', encoding='utf-8')
            page.set_input_files('#load-file', str(bad))
            page.wait_for_function("document.getElementById('state-notice').textContent.indexOf('not valid JSON') >= 0", timeout=5000)
            self.assertEqual(page.evaluate("document.getElementById('load-file').value"), '')
        self.assertClean()


if __name__ == '__main__':
    unittest.main()
