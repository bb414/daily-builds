"""Drives the browser app in headless Chromium (skipped if Playwright is not installed)."""

import unittest
from pathlib import Path

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
        page.wait_for_selector("#summary .range")
        return page

    def settle(self, page):
        page.wait_for_timeout(450)

    def test_loads_with_results_and_no_requests(self):
        page = self.open()
        text = page.inner_text("#summary")
        self.assertIn("most likely between", text)
        self.assertIn("chance of clearing", text)
        self.assertEqual(page.locator("#dist-card rect.bar").count() > 10, True)
        self.assertEqual(page.locator("#tornado-card rect.bar").count(), 6)
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith(("file:", "data:", "blob:")) for u in self.requests), self.requests)
        page.close()

    def test_switching_templates(self):
        page = self.open()
        page.select_option("#template", "ai-assistant")
        self.settle(page)
        self.assertEqual(page.input_value("#f-title"), "An AI assistant for a support team")
        self.assertIn("Net value per year", page.inner_text("#summary"))
        self.assertEqual(page.locator(".term").count(), 3)
        self.assertEqual(page.locator(".term.minus").count(), 2)
        page.close()

    def test_editing_a_range_updates_the_results(self):
        page = self.open()
        before = page.inner_text("#summary .range")
        page.fill(".driver[data-t='0'][data-d='2'] [data-f='high']", "60")
        self.settle(page)
        self.assertNotEqual(page.inner_text("#summary .range"), before)
        self.assertEqual(self.errors, [])
        page.close()

    def test_invalid_input_explains_the_problem(self):
        page = self.open()
        page.fill(".driver[data-t='0'][data-d='0'] [data-f='low']", "40000")
        self.settle(page)
        self.assertTrue(page.is_visible("#problems"))
        self.assertIn("low value must be below the high value", page.inner_text("#problems"))
        self.assertEqual(page.get_attribute(".driver[data-t='0'][data-d='0'] [data-f='low']", "aria-invalid"), "true")
        page.fill(".driver[data-t='0'][data-d='0'] [data-f='low']", "20000")
        self.settle(page)
        self.assertTrue(page.is_hidden("#problems"))
        self.assertIsNone(page.get_attribute(".driver[data-t='0'][data-d='0'] [data-f='low']", "aria-invalid"))
        page.close()

    def test_adding_and_removing_drivers_and_terms(self):
        page = self.open()
        page.click("#add-term")
        self.assertEqual(page.locator(".term").count(), 2)
        self.settle(page)
        self.assertIn("needs a name", page.inner_text("#problems"))
        page.fill(".driver[data-t='1'][data-d='0'] [data-f='name']", "Gift boxes")
        page.select_option("#t1sign", "-1")
        self.settle(page)
        self.assertTrue(page.is_hidden("#problems"))
        self.assertEqual(page.locator(".term.minus").count(), 1)
        page.click(".term[data-t='1'] [data-act='del-driver']")
        self.settle(page)
        self.assertIn("needs at least one driver", page.inner_text("#problems"))
        page.click(".term[data-t='1'] [data-act='del-term']")
        self.settle(page)
        self.assertTrue(page.is_hidden("#problems"))
        page.select_option(".driver[data-t='0'][data-d='5'] [data-f='dist']", "fixed")
        self.settle(page)
        self.assertTrue(page.is_disabled(".driver[data-t='0'][data-d='5'] [data-f='high']"))
        self.assertEqual(page.locator("#tornado-card rect.bar").count(), 5)
        self.assertEqual(self.errors, [])
        page.close()

    def test_what_to_check_first(self):
        page = self.open()
        text = page.inner_text("#voi-card")
        self.assertIn("What to check before deciding", text)
        self.assertIn("go ahead", text)
        self.assertIn("Share who would try a meal kit", page.inner_text("#voi-card tbody tr:first-child"))
        page.fill("#f-threshold", "")
        self.settle(page)
        self.assertIn("Add a threshold", page.inner_text("#voi-card"))
        self.assertNotIn("chance of clearing", page.inner_text("#summary"))
        page.fill("#f-threshold", "5")
        self.settle(page)
        self.assertIn("nothing worth checking first", page.inner_text("#voi-card"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_narrowing_a_range(self):
        page = self.open()
        card = page.inner_text("#narrow-card")
        self.assertIn("Try narrowing a range", card)
        self.assertIn("Share who would try a meal kit", page.input_value("#narrow-driver") and
                      page.inner_text("#narrow-driver option:checked"))
        before = page.inner_text("#narrow-card tbody tr:nth-child(2)")
        page.select_option("#narrow-factor", "0")
        after = page.inner_text("#narrow-card tbody tr:nth-child(2)")
        self.assertNotEqual(before, after)
        self.assertIn("Pinning down", page.inner_text("#narrow-card"))
        self.assertEqual(page.evaluate("document.activeElement.id"), "narrow-factor")
        self.assertEqual(self.errors, [])
        page.close()

    def test_download_open_link_and_autosave(self):
        import json
        import tempfile
        page = self.open()
        page.select_option("#template", "bike-share")
        self.settle(page)
        page.fill("#f-title", "My bikes")
        self.settle(page)
        self.assertEqual(page.input_value("#template"), "yours")
        with page.expect_download() as info:
            page.click("#save-btn")
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.json"
            info.value.save_as(str(path))
            saved = json.loads(path.read_text())
            self.assertEqual(saved["title"], "My bikes")
            self.assertNotIn("key", saved)
            from rangefinder.model import validate_model
            self.assertEqual(validate_model(saved), [])
            # Reloading restores the last estimate from this browser.
            page.reload()
            page.wait_for_selector("#summary .range")
            self.assertEqual(page.input_value("#f-title"), "My bikes")
            # Opening a file, then a broken one.
            saved["title"] = "Opened from a file"
            path.write_text(json.dumps(saved))
            page.set_input_files("#open-file", str(path))
            page.wait_for_function("document.querySelector('#f-title').value === 'Opened from a file'")
            bad = Path(d) / "bad.json"
            bad.write_text('{"format": "range-finder-model", "terms": []}')
            page.set_input_files("#open-file", str(bad))
            page.wait_for_selector("#status.error")
            self.assertIn("could not be opened", page.inner_text("#status"))
        # A share link reproduces the estimate in a fresh browser.
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        page.click("#link-btn")
        link = page.evaluate("location.href")
        self.assertIn("#model=", link)
        other = self.browser.new_page()
        other.goto(link)
        other.wait_for_selector("#summary .range")
        self.assertEqual(other.input_value("#f-title"), "Opened from a file")
        self.assertEqual(other.inner_text("#summary .range"), page.inner_text("#summary .range"))
        other.goto(APP_URL + "#model=not-base64!")
        other.close()
        self.assertEqual(self.errors, [])
        page.close()

    def test_switching_away_from_your_estimate_asks_first(self):
        page = self.open()
        page.fill("#f-title", "Mine")
        self.settle(page)
        page.once("dialog", lambda d: d.dismiss())
        page.select_option("#template", "bike-share")
        self.assertEqual(page.input_value("#template"), "yours")
        self.assertEqual(page.input_value("#f-title"), "Mine")
        page.once("dialog", lambda d: d.accept())
        page.select_option("#template", "bike-share")
        self.settle(page)
        self.assertEqual(page.input_value("#f-title"), "A campus e-bike share")
        page.close()

    def test_changing_a_percentage_to_fixed_converts_it(self):
        page = self.open()
        sel = ".driver[data-t='0'][data-d='1'] [data-f='dist']"
        page.select_option(sel, "fixed")
        self.settle(page)
        self.assertEqual(page.input_value(".driver[data-t='0'][data-d='1'] [data-f='low']"), "0.55")
        self.assertTrue(page.is_hidden("#problems"))
        self.assertIn("£", page.inner_text("#summary .range"))
        self.assertNotIn("m", page.inner_text("#summary .range").replace("and", ""))  # still thousands, not millions
        page.select_option(sel, "share")
        self.settle(page)
        self.assertEqual(page.input_value(".driver[data-t='0'][data-d='1'] [data-f='low']"), "55")
        page.close()

    def test_narrowing_with_an_invalid_model_does_not_throw(self):
        page = self.open()
        page.wait_for_selector("#narrow-factor")
        page.fill(".driver[data-t='0'][data-d='0'] [data-f='low']", "")
        self.settle(page)
        page.select_option("#narrow-factor", "0")
        page.wait_for_timeout(200)
        self.assertEqual(self.errors, [])
        page.close()

    def test_labels_follow_the_driver_name(self):
        page = self.open()
        page.fill(".driver[data-t='0'][data-d='0'] [data-f='name']", "Undergraduates")
        self.assertEqual(page.get_attribute(".driver[data-t='0'][data-d='0'] [data-f='low']", "aria-label"),
                         "Low value for Undergraduates")
        self.assertEqual(page.get_attribute(".driver[data-t='0'][data-d='0'] [data-act='del-driver']", "aria-label"),
                         "Remove Undergraduates")
        page.close()

    def test_huge_numbers_do_not_break_the_charts(self):
        import json
        import tempfile
        model = {"format": "range-finder-model", "version": 1, "title": "Huge", "outputName": "x", "unit": "",
                 "unitPosition": "prefix", "threshold": None, "terms": [
                     {"name": "a", "sign": 1, "drivers": [{"name": "big", "dist": "fixed", "low": 1e14, "high": 1e14, "unit": ""},
                                                          {"name": "n", "dist": "normal", "low": 1, "high": 3, "unit": ""}]},
                     {"name": "b", "sign": 1, "drivers": [{"name": "c", "dist": "fixed", "low": 1e15, "high": 1e15, "unit": ""}]}]}
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "huge.json"
            f.write_text(json.dumps(model))
            page = self.open()
            page.set_input_files("#open-file", str(f))
            page.wait_for_function("document.querySelector('#f-title').value === 'Huge'")
            self.settle(page)
            self.assertIn("1000tn+", page.inner_text("#summary"))
            self.assertEqual(page.evaluate("document.querySelectorAll('svg [x=\"NaN\"], svg [width=\"NaN\"]').length"), 0)
            self.assertEqual(self.errors, [])
            page.close()

    def test_link_is_cleared_so_later_edits_survive_a_reload(self):
        page = self.open()
        page.fill("#f-title", "Linked")
        self.settle(page)
        page.click("#link-btn")
        page.wait_for_timeout(200)
        link = page.evaluate("location.href")
        if "#model=" not in link:   # the clipboard worked, so the address bar was tidied; rebuild the link
            link = page.evaluate("location.href.split('#')[0] + '#model=' + btoa(unescape(encodeURIComponent(JSON.stringify(Object.assign(JSON.parse(localStorage.getItem('range-finder-model-v1')).model, {}))))).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'')")
        other = self.browser.new_page()
        other.goto(link)
        other.wait_for_selector("#summary .range")
        self.assertNotIn("#model=", other.evaluate("location.href"))
        other.fill("#f-title", "Edited after opening")
        other.wait_for_timeout(450)
        other.reload()
        other.wait_for_selector("#summary .range")
        self.assertEqual(other.input_value("#f-title"), "Edited after opening")
        other.close()
        page.close()

    def test_untouched_example_is_not_your_estimate_after_a_reload(self):
        page = self.open()
        page.select_option("#template", "ai-assistant")
        self.settle(page)
        page.reload()
        page.wait_for_selector("#summary .range")
        self.assertEqual(page.input_value("#template"), "ai-assistant")
        dialogs = []
        page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
        page.select_option("#template", "meal-kits")
        self.settle(page)
        self.assertEqual(dialogs, [])
        self.assertEqual(page.input_value("#f-title"), "Meal kits for students in Wealdham")
        page.close()

    def test_second_audit_details(self):
        import json
        import tempfile
        page = self.open()
        # A name of only a non-breaking space counts as a name, as in validation.
        page.fill(".driver[data-t='0'][data-d='0'] [data-f='name']", "\u00a0")
        self.settle(page)
        self.assertTrue(page.is_hidden("#problems"))
        self.assertIsNone(page.get_attribute(".driver[data-t='0'][data-d='0'] [data-f='name']", "aria-invalid"))
        # Renaming a term updates its delete button, and percentage fields say so.
        page.fill("#t0name", "Student spending")
        self.assertEqual(page.get_attribute(".term[data-t='0'] [data-act='del-term']", "aria-label"), "Remove the term Student spending")
        self.assertEqual(page.get_attribute(".driver[data-t='0'][data-d='1'] [data-f='low']", "aria-label"),
                         "Low value (%) for Share in self-catered housing")
        self.settle(page)
        # Opening a file keeps the edited estimate so it can be restored.
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "bikes.json"
            from rangefinder.model import TEMPLATES
            f.write_text(json.dumps(TEMPLATES[2]))
            page.set_input_files("#open-file", str(f))
            page.wait_for_function("document.querySelector('#f-title').value === 'A campus e-bike share'")
            self.assertIn("previous estimate is kept", page.inner_text("#status"))
            page.click("#status button")
            page.wait_for_function("document.querySelector('#t0name').value === 'Student spending'")
        self.assertEqual(self.errors, [])
        page.close()

    def test_phone_layout_fits(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        box_results = page.locator(".results").bounding_box()
        box_editor = page.locator(".editor").bounding_box()
        self.assertLess(box_results["y"], box_editor["y"])  # results come first on a phone
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
