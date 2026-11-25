"""Drives the browser app in headless Chromium. Skipped when Playwright for Python is not installed."""

import json
import os
import tempfile
import unittest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - optional dependency
    sync_playwright = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "file://" + os.path.join(ROOT, "app", "index.html")


@unittest.skipIf(sync_playwright is None, "Playwright for Python is not installed")
class UiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # no browser available
            cls.pw.stop()
            raise unittest.SkipTest("no Chromium available: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, url=URL):
        page = self.browser.new_page(viewport={"width": width, "height": 900}, accept_downloads=True)
        self.problems = []
        page.on("console", lambda m: self.problems.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.problems.append(str(e)))
        page.on("request", lambda r: self.problems.append("request " + r.url)
                if not r.url.startswith(("file:", "data:", "blob:")) else None)
        page.goto(url)
        page.wait_for_selector("#strat-rows tr")
        return page

    def test_loads_cleanly_and_fits_a_phone(self):
        for width in (1280, 390):
            page = self.open(width)
            self.assertEqual(page.evaluate("document.documentElement.scrollWidth"), width)
            self.assertEqual(page.locator("#strat-rows tr").count(), 5)
            self.assertEqual(page.locator("#weekly-rows tr").count(), 6)
            page.close()
        self.assertEqual(self.problems, [])

    def test_every_control_has_a_label(self):
        page = self.open()
        unlabelled = page.evaluate("""() => [...document.querySelectorAll('input, select, button')].filter(e => {
            if (e.type === 'radio') return !e.closest('label');
            if (e.type === 'file') return !e.closest('label');
            if (e.tagName === 'BUTTON') return !(e.textContent.trim() || e.getAttribute('aria-label'));
            return !(e.labels && e.labels.length) && !e.getAttribute('aria-label');
        }).map(e => e.outerHTML.slice(0, 80))""")
        self.assertEqual(unlabelled, [])
        page.close()

    def test_fixing_a_payment_teaches_the_app(self):
        page = self.open()
        page.click("input[value=graduate]")
        page.wait_for_timeout(200)
        before = page.inner_text("#kpis")
        page.select_option("#filter", "wrong")
        page.locator("#rows tr", has_text="REF RENT").first.get_by_role("button").click()
        status = page.inner_text("#status")
        self.assertIn("as Bills", status)
        self.assertIn("now right", status)
        self.assertNotEqual(before, page.inner_text("#kpis"))
        self.assertIn("1", page.inner_text("#kpis .kpi:last-child .v"))
        page.click("#ask")
        self.assertIn("The app would ask about", page.inner_text("#status"))
        self.assertEqual(page.locator("#rows tr.flash").count(), 1)
        page.click("#reset")
        self.assertIn("0", page.inner_text("#kpis .kpi:last-child .v"))
        page.close()
        self.assertEqual(self.problems, [])

    def test_robustness_replay(self):
        page = self.open()
        page.click("#robust-run")
        page.wait_for_selector("#robust-out:not([hidden])", timeout=30000)
        self.assertEqual(page.locator("#robust-rows tr").count(), 5)
        self.assertIn("of 20", page.inner_text("#robust-rows"))
        page.close()

    def test_settings_survive_a_link_and_a_file(self):
        page = self.open(url=URL + "#persona=sixthformer&weeks=8&seed=5&weight=10&target=7&checks=40&slip=2&perweek=4")
        self.assertTrue(page.is_checked("input[value=sixthformer]"))
        self.assertEqual(page.input_value("#weeks"), "8")
        self.assertEqual(page.input_value("#perweek"), "4")
        self.assertIn("weeks=8", page.evaluate("location.hash"))
        page.locator("#rows tr button").first.click()
        with page.expect_download() as info:
            page.click("#savefile")
        path = os.path.join(tempfile.mkdtemp(), "saved.json")
        info.value.save_as(path)
        with open(path) as fh:
            saved = json.load(fh)
        self.assertEqual(saved["settings"]["persona"], "sixthformer")
        self.assertEqual(len(saved["checks"]), 1)
        page.close()
        page = self.open()
        page.set_input_files("#loadfile", path)
        page.wait_for_function("document.getElementById('keep-msg').textContent.includes('Loaded')")
        self.assertIn("1 check", page.inner_text("#keep-msg"))
        self.assertTrue(page.is_checked("input[value=sixthformer]"))
        saved["checks"] += [{"id": 1.5, "desc": "X", "pot": "Fun"}, None, {"id": 0, "desc": "WRONG", "pot": "Fun"},
                            {"id": 2, "desc": saved["checks"][0]["desc"], "pot": "Nonsense"}]
        with open(path, "w") as fh:
            json.dump(saved, fh)
        page.set_input_files("#loadfile", path)
        page.wait_for_function("document.getElementById('keep-msg').textContent.includes('skipped 4')")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("not json")
        page.set_input_files("#loadfile", fh.name)
        page.wait_for_function("document.getElementById('keep-msg').textContent.includes('not valid')")
        os.unlink(fh.name)
        page.close()
        self.assertEqual(self.problems, [])
        page = self.open(url=URL + "#persona=nobody&weeks=999&seed=-4&checks=abc")
        self.assertTrue(page.is_checked("input[value=student]"))
        self.assertEqual(page.input_value("#weeks"), "26")
        self.assertEqual(page.input_value("#seed"), "1")
        page.close()


if __name__ == "__main__":
    unittest.main()
