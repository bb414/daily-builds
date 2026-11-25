"""Drives the browser app in headless Chromium: no errors, no network, the
main interactions work, every control has a name, and nothing is wider than
a phone screen. Skipped when Playwright is not installed."""

import json
import os
import tempfile
import unittest
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "file://" + os.path.join(ROOT, "app", "index.html")

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

UNNAMED_CONTROLS = """
() => Array.from(document.querySelectorAll('input, select, button, textarea')).filter(e => {
  if (e.closest('[hidden]')) return false;
  const label = e.labels && e.labels.length ? e.labels[0].textContent.trim() : '';
  return !(label || e.getAttribute('aria-label') || (e.tagName === 'BUTTON' && e.textContent.trim()));
}).map(e => e.outerHTML.slice(0, 80))
"""


@unittest.skipIf(sync_playwright is None, "Playwright for Python is not installed")
class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280):
        page = self.browser.new_page(viewport={"width": width, "height": 900})
        self.errors = []
        self.requests = []
        page.on("console", lambda m: self.errors.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url) if not r.url.startswith("file:") else None)
        page.goto(URL)
        page.wait_for_selector("#plans .plan")
        return page

    def tearDown(self):
        self.assertEqual(self.errors, [], "console errors")
        self.assertEqual(self.requests, [], "network requests")

    def test_route_flips_the_decision(self):
        page = self.open()
        self.assertIn("Not shortlisted", page.inner_text("#decision"))
        page.click("#plans .plan button")
        page.wait_for_function("document.querySelector('#decision .verdict').textContent === 'Shortlisted'")
        self.assertNotIn("Not shortlisted", page.inner_text("#decision"))
        self.assertIn("nothing to change", page.inner_text("#plans"))
        page.close()

    def test_presets_and_inputs(self):
        page = self.open()
        self.assertEqual(page.locator("#preset option").count(), 8)
        page.select_option("#preset", label="No route within a year")
        self.assertIn("No route within these limits", page.inner_text("#plans"))
        page.select_option("#preset", label="Near miss")
        page.fill("#f-test", "95")
        page.press("#f-test", "Enter")
        page.locator("#f-test").blur()
        page.wait_for_function("document.querySelector('#decision .verdict').textContent === 'Shortlisted'")
        self.assertEqual(page.input_value("#preset"), "")
        page.fill("#f-test", "-40")
        page.locator("#f-test").blur()
        self.assertEqual(page.input_value("#f-test"), "0")
        page.fill("#f-experience", "")
        page.locator("#f-experience").blur()
        self.assertEqual(page.input_value("#f-experience"), "7")
        page.fill("#cap-1", "")
        page.locator("#cap-1").blur()
        self.assertEqual(page.input_value("#cap-1"), "12")
        page.fill("#cap-1", "500")
        page.locator("#cap-1").blur()
        self.assertEqual(page.input_value("#cap-1"), "36")
        page.close()

    def test_rules_change_the_routes(self):
        page = self.open()
        before = page.inner_text("#plans")
        page.uncheck("#act-0")
        after = page.inner_text("#plans")
        self.assertNotEqual(before, after)
        self.assertNotIn("Test score:", after)
        page.close()

    def test_tabs_and_keyboard(self):
        page = self.open()
        page.focus("#tab-applicant")
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.get_attribute("#tab-cohort", "aria-selected"), "true")
        self.assertFalse(page.is_hidden("#panel-cohort"))
        self.assertTrue(page.is_hidden("#panel-applicant"))
        self.assertEqual(page.locator("#kpis .kpi").count(), 4)
        self.assertEqual(page.locator("#hist svg rect").count(), 14)
        page.keyboard.press("ArrowRight")
        self.assertFalse(page.is_hidden("#panel-hold"))
        page.keyboard.press("End")
        self.assertFalse(page.is_hidden("#panel-about"))
        page.close()

    def test_hold_tab_and_route_checks(self):
        page = self.open()
        cards = page.locator("#plans .plan .hold")
        self.assertGreater(cards.count(), 0)
        self.assertRegex(cards.first.inner_text(), "^(Still works|Breaks) after next year")
        page.click("#tab-hold")
        self.assertEqual(page.locator("#holdTable tbody tr").count(), 7)
        before = page.inner_text("#holdTable")
        page.click("#retrainNext")
        self.assertEqual(page.inner_text("#retrainOut"), "2")
        self.assertNotEqual(before, page.inner_text("#holdTable"))
        page.fill("#points", "4")
        page.dispatch_event("#points", "change")
        self.assertIn("+4 test points", page.inner_text("#pointsOut"))
        page.click("#tab-applicant")
        page.select_option("#margin", "0.3")
        self.assertIn("aim for 0.8", page.inner_text("#margin"))
        page.close()

    def test_notice_and_copy(self):
        page = self.open()
        text = page.inner_text("#notice")
        self.assertIn("Outcome: not shortlisted", text)
        self.assertIn("Route A: an aptitude test score of 66 instead of 64.", text)
        page.click("#copyNotice")
        page.wait_for_function("document.getElementById('noticeMsg').textContent !== ''", timeout=3000)
        self.assertRegex(page.inner_text("#noticeMsg"), "Copied|Could not copy")
        page.close()

    def test_setup_download_load_and_link(self):
        page = self.open()
        page.uncheck("#act-0")
        with page.expect_download() as info:
            page.click("#saveSetup")
        saved = json.loads(open(info.value.path(), encoding="utf-8").read())
        self.assertEqual(saved["tool"], "what-would-it-take")
        self.assertFalse(saved["rules"]["test"]["canChange"])
        saved["applicant"]["test"] = 90
        saved["rules"]["experience"]["weight"] = 2.5
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, "good.json")
            with open(good, "w", encoding="utf-8") as fh:
                json.dump(saved, fh)
            page.set_input_files("#loadSetup", good)
            page.wait_for_function("document.getElementById('setupMsg').textContent.startsWith('Loaded')")
            self.assertEqual(page.input_value("#f-test"), "90")
            self.assertEqual(page.input_value("#w-1"), "2.5")
            self.assertFalse(page.is_checked("#act-0"))
            bad = os.path.join(d, "bad.json")
            with open(bad, "w", encoding="utf-8") as fh:
                fh.write('{"applicant": {"gap": 99}}')
            page.set_input_files("#loadSetup", bad)
            page.wait_for_function("document.getElementById('setupMsg').textContent.startsWith('Could not')")
            self.assertIn("applicant.gap", page.inner_text("#setupMsg"))
            self.assertEqual(page.input_value("#f-test"), "90")
        page.close()
        link = {"applicant": {"test": 47, "experience": 24, "projects": 3, "certs": 0, "degree": 3, "gap": 0},
                "margin": 0.1, "nextYear": {"points": 2, "retrain": 3}}
        page = self.browser.new_page()
        page.goto(URL + "#setup=" + quote(json.dumps(link)))
        page.wait_for_selector("#plans .plan")
        self.assertEqual(page.input_value("#f-experience"), "24")
        self.assertEqual(page.input_value("#margin"), "0.1")
        self.assertEqual(page.input_value("#preset"), "4")
        page.click("#tab-hold")
        self.assertEqual(page.inner_text("#retrainOut"), "3")
        page.goto(URL + "#setup=%7Bbroken")
        page.wait_for_function("document.getElementById('setupMsg').textContent.includes('damaged')", timeout=3000)
        page.close()

    def test_explanation_gap_card(self):
        page = self.open()
        page.click("#tab-cohort")
        self.assertEqual(page.locator("#gapKpis .kpi").count(), 2)
        self.assertGreater(page.locator("#gapMatrix tbody tr").count(), 3)
        page.close()

    def test_every_control_has_a_name(self):
        page = self.open()
        for tab in ("#tab-applicant", "#tab-cohort", "#tab-hold", "#tab-about"):
            page.click(tab)
            self.assertEqual(page.evaluate(UNNAMED_CONTROLS), [], tab)
        page.close()

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(390)
        for tab in ("#tab-applicant", "#tab-cohort", "#tab-hold", "#tab-about"):
            page.click(tab)
            page.wait_for_timeout(50)
            width = page.evaluate("document.documentElement.scrollWidth")
            self.assertLessEqual(width, 390, tab)
        page.close()


if __name__ == "__main__":
    unittest.main()
