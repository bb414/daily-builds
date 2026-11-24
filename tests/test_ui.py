"""Drives the browser app in headless Chromium (skipped if Playwright is not installed)."""

import json
import tempfile
import unittest
from pathlib import Path

from saveorsink import model as M

ROOT = Path(__file__).resolve().parents[1]
APP_URL = (ROOT / "app" / "index.html").as_uri()

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("Chromium is not available: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.errors, self.requests = [], []
        page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(APP_URL)
        page.wait_for_selector("#table-card table")
        return page

    def settle(self, page):
        page.wait_for_timeout(400)

    def test_loads_with_results_and_no_requests(self):
        page = self.open()
        self.assertIn("The verdict", page.inner_text("#verdict-card"))
        self.assertEqual(page.locator("#table-card tbody tr").count(), len(M.RULES))
        self.assertTrue(page.locator("#year-card path.bal").count() == 1)
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith(("file:", "data:", "blob:")) for u in self.requests), self.requests)
        page.close()

    def test_changing_a_setting_updates_the_results(self):
        page = self.open()
        before = page.inner_text("#table-card tbody")
        page.select_option("#c-rescue", "never")
        self.settle(page)
        after = page.inner_text("#table-card tbody")
        self.assertNotEqual(before, after)
        page.locator("#c-rent").fill("900")
        self.settle(page)
        self.assertIn("£900", page.inner_text("#c-rent-out"))
        self.assertNotEqual(after, page.inner_text("#table-card tbody"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_presets_and_the_year_view(self):
        page = self.open()
        page.select_option("#preset", "tight")
        self.settle(page)
        self.assertEqual(page.input_value("#c-loanPerTerm"), "3600")
        page.click("[data-view='weekly']")
        self.assertEqual(page.get_attribute("[data-view='weekly']", "aria-pressed"), "true")
        first = page.inner_text("#year-card .facts")
        page.click("#next-year")
        self.assertIn("Year 2 of", page.inner_text("#year-desc"))
        self.assertNotEqual(first, page.inner_text("#year-card .facts"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_tuning_map(self):
        page = self.open()
        page.wait_for_selector("#tune-out table.map")
        self.assertEqual(page.locator("#tune-out table.map button").count(), 25)
        self.assertEqual(page.locator("#tune-out button.here").count(), 1)
        self.assertEqual(page.locator("#tune-out button.front").count(), 1)
        page.select_option("#preset", "tight")
        page.select_option("#c-rescue", "never")
        page.wait_for_timeout(1200)
        self.assertIn("Looks ahead", page.inner_text(".tune-lead"))
        page.click("details[data-group='Saving rules'] > summary")
        page.click("#tune-out button[data-a='56'][data-b='400']")
        page.wait_for_timeout(1200)
        # The group the reader opened stays open when the controls are redrawn.
        self.assertTrue(page.evaluate("document.querySelector(\"details[data-group='Saving rules']\").open"))
        self.assertEqual(page.input_value("#c-smart-horizon"), "56")
        self.assertEqual(page.input_value("#c-smart-buffer"), "400")
        self.assertIn("Your current settings", page.get_attribute("#tune-out button.here", "aria-label"))
        self.assertEqual(page.evaluate("document.activeElement.dataset.a"), "56")
        page.click("[data-tune='planner']")
        page.wait_for_timeout(800)
        self.assertEqual(page.locator("#tune-out table.map button").count(), 20)
        self.assertIn("share of spare money saved", page.inner_text("#tune-out").lower())
        self.assertEqual(self.errors, [])
        page.close()

    def test_save_open_and_link(self):
        page = self.open()
        page.select_option("#preset", "shifts")
        page.locator("#c-rent").fill("610")
        self.settle(page)
        with page.expect_download() as info:
            page.click("#save-file")
        saved = json.loads(Path(info.value.path()).read_text())
        self.assertEqual(saved["rent"], 610)
        self.assertEqual(M.validate_settings(saved), [])
        saved["rent"] = 700
        with tempfile.TemporaryDirectory() as d:
            good, bad = Path(d) / "good.json", Path(d) / "bad.json"
            good.write_text("\ufeff" + json.dumps(saved), encoding="utf-8")
            bad.write_text(json.dumps(dict(saved, rent=-5)), encoding="utf-8")
            page.set_input_files("#file-in", str(good))
            page.wait_for_timeout(600)
            self.assertEqual(page.input_value("#c-rent"), "700")
            self.assertIn("Opened good.json", page.inner_text("#io-msg"))
            self.assertEqual(page.evaluate("document.activeElement.id"), "open-file")
            page.set_input_files("#file-in", str(bad))
            page.wait_for_timeout(300)
            self.assertIn("rent must be", page.inner_text("#io-msg"))
            self.assertEqual(page.input_value("#c-rent"), "700")
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.click("#copy-link")
        page.wait_for_timeout(300)
        url = page.evaluate("location.href")
        self.assertIn("#s=", url)
        self.assertEqual(M.decode_link(url)["rent"], 700)
        page.close()
        page = self.browser.new_page()
        page.goto(APP_URL + "#" + M.encode_link(dict(M.default_settings("tight"), rent=333)))
        page.wait_for_selector("#table-card table")
        self.assertEqual(page.input_value("#c-rent"), "333")
        self.assertEqual(page.input_value("#preset"), "tight")
        page.goto(APP_URL + "#" + M.encode_link(dict(M.default_settings("tight"), rent=333, preset="mine")))
        page.wait_for_timeout(500)
        self.assertEqual(page.input_value("#preset"), "custom")
        page.goto(APP_URL + "#" + M.encode_link(dict(M.default_settings("tight"), rent=333)))
        page.wait_for_timeout(500)
        self.assertIn("Opened the settings in the link", page.inner_text("#io-msg"))
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "other.json"
            f.write_text(json.dumps(dict(M.default_settings("steady"), rent=777)), encoding="utf-8")
            page.set_input_files("#file-in", str(f))
            page.wait_for_timeout(600)
        # Opening a file replaces the settings from the link, so the old link leaves the address bar.
        self.assertEqual(page.input_value("#c-rent"), "777")
        self.assertNotIn("#", page.evaluate("location.href"))
        page.goto(APP_URL + "#" + M.encode_link(dict(M.default_settings("tight"), rent=333)))
        page.wait_for_timeout(500)
        self.assertEqual(page.input_value("#c-rent"), "333")
        page.locator("#c-rent").fill("400")
        self.settle(page)
        self.assertNotIn("#", page.evaluate("location.href"))
        # A new link pasted into the same tab is picked up too.
        page.goto(APP_URL + "#" + M.encode_link(dict(M.default_settings("shifts"), rent=444)))
        page.wait_for_timeout(500)
        self.assertEqual(page.input_value("#c-rent"), "444")
        page.goto(APP_URL + "#s=abc")
        page.wait_for_timeout(300)
        self.assertIn("damaged", page.inner_text("#io-msg"))
        self.assertEqual(page.input_value("#c-rent"), "444")
        page.close()
        page = self.browser.new_page()
        page.goto(APP_URL + "#s=abc")
        page.wait_for_selector("#table-card table")
        self.assertIn("damaged", page.inner_text("#io-msg"))
        self.assertEqual(page.input_value("#preset"), "steady")
        page.close()

    def test_verdict_never_recommends_a_rule_that_costs_money(self):
        page = self.open()
        page.select_option("#preset", "tight")
        page.locator("#c-overdraftLimit").fill("0")
        page.select_option("#c-rescue", "never")
        page.wait_for_timeout(800)
        text = page.inner_text("#verdict-card")
        self.assertNotIn("Smart saver leaves the most", text)
        for line in text.splitlines():
            if "leaves the most set aside" in line:
                rule = line.split(", ", 1)[1].split(" leaves")[0]
                self.assertNotIn(rule + " leave", text.split(line, 1)[1])
        page.close()

    def test_map_shows_days_when_every_year_goes_past_the_limit(self):
        page = self.open()
        page.select_option("#c-rescue", "never")
        page.locator("#c-overdraftLimit").fill("0")
        page.wait_for_timeout(1500)
        self.assertIn("for how long", page.inner_text(".tune-lead"))
        self.assertIn("days past", page.inner_text("#tune-out table.map"))
        label = page.get_attribute("#tune-out button.front", "aria-label")
        self.assertIn("days a year on average", label)
        page.locator("#c-startBalance").fill("-1000")
        self.assertEqual(page.inner_text("#c-startBalance-out"), "-£1,000")
        self.assertEqual(self.errors, [])
        page.close()

    def test_phone_layout_fits(self):
        page = self.open(390, 844)
        page.wait_for_selector("#tune-out table.map")
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        self.assertLessEqual(page.locator("#tune-out table.map").bounding_box()["width"],
                             page.locator("#tune-card").bounding_box()["width"])
        self.assertLess(page.locator(".results").bounding_box()["y"], page.locator(".settings").bounding_box()["y"])
        page.close()

    def test_every_control_has_a_name(self):
        page = self.open()
        unnamed = page.evaluate("""() => [...document.querySelectorAll('button, select, input')]
            .filter(el => {
              const label = el.labels && el.labels.length ? el.labels[0].textContent : '';
              return !(el.getAttribute('aria-label') || el.textContent.trim() || label.trim());
            }).map(el => el.outerHTML)""")
        self.assertEqual(unnamed, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
