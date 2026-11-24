"""Drive the browser app in headless Chromium. Skipped without Playwright for Python."""

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
APP_URL = (ROOT / "app" / "index.html").as_uri()

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover
            cls.pw.stop()
            raise unittest.SkipTest("No browser available for Playwright: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.errors, self.requests = [], []
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(APP_URL)
        page.fill("#a-asof", "2026-11-24")
        page.dispatch_event("#a-asof", "change")
        return page

    def test_default_example(self):
        page = self.open()
        self.assertIn("High-risk (Annex III use)", page.inner_text("#tier"))
        self.assertIn("Art 6(2)", page.inner_text("#trace"))
        self.assertIn("in 373 days", page.inner_text("#obligations"))
        self.assertIn("2 December 2027", page.inner_text("#kpis"))
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith("file://") for u in self.requests), self.requests)
        page.close()

    def test_every_example_classifies(self):
        page = self.open()
        expected = {"shortlister": "High-risk", "helpdesk": "Transparency duties", "moodMonitor": "Banned practice",
                    "loanEngine": "High-risk", "benefits": "High-risk", "transcript": "Annex III use, but not high-risk",
                    "insulin": "High-risk (product under Annex I)", "openModel": "General-purpose AI model", "invoices": "Minimal risk"}
        for key, label in expected.items():
            page.select_option("#preset", key)
            self.assertIn(label, page.inner_text("#tier"), key)
        page.select_option("#preset", "benefits")
        self.assertIn("fundamental rights impact assessment", page.inner_text("#obligations"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_answers_change_the_result(self):
        page = self.open()
        page.check("#ban-socialScoring")
        self.assertIn("Banned practice", page.inner_text("#tier"))
        self.assertEqual(page.input_value("#preset"), "")
        page.uncheck("#ban-socialScoring")
        page.select_option("#a-derogation", "procedural")
        self.assertIn("High-risk", page.inner_text("#tier"), "profiling blocks the exemption")
        page.uncheck("#a-profiling")
        self.assertIn("not high-risk", page.inner_text("#tier"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_timeline_shows_the_omnibus_moves(self):
        page = self.open()
        self.assertIn("2 August 2026 moved to 2 December 2027, 487 more days", page.inner_text("#omni"))
        self.assertEqual(page.locator("#timeline svg").count(), 1)
        self.assertIn("originally 2 August 2026", page.get_attribute("#timeline svg", "aria-label"))
        page.select_option("#preset", "invoices")
        self.assertIn("did not change the dates", page.inner_text("#omni"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_register_and_roadmap(self):
        page = self.open()
        page.evaluate("window.localStorage.clear()")
        page.reload()
        self.assertIn("The register is empty", page.inner_text("#register"))
        page.click("#reg-add")
        self.assertEqual(page.locator("#register tbody tr").count(), 1)
        page.click("#reg-add")
        self.assertEqual(page.locator("#register tbody tr").count(), 1, "the same name updates the row")
        self.assertIn("Updated", page.inner_text("#reg-msg"))
        page.click("#reg-examples")
        self.assertEqual(page.locator("#register tbody tr").count(), 9)
        self.assertIn("2 December 2027", page.inner_text("#roadmap-table"))
        self.assertEqual(page.locator("#roadmap svg").count(), 1)
        page.reload()
        self.assertEqual(page.locator("#register tbody tr").count(), 9, "kept in this browser")
        page.locator("#register tbody tr").nth(3).get_by_role("button", name="Open").click()
        self.assertIn("Loan decision engine", page.input_value("#a-name"))
        self.assertIn("High-risk", page.inner_text("#tier"))
        page.locator("#register tbody tr").nth(0).get_by_role("button", name="Remove").click()
        self.assertEqual(page.locator("#register tbody tr").count(), 8)
        page.once("dialog", lambda d: d.accept())
        page.click("#reg-clear")
        self.assertIn("The register is empty", page.inner_text("#register"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_pivots_and_try_it(self):
        page = self.open()
        self.assertIn("20 changes tried, 10 made a difference", page.inner_text("#piv-sub"))
        first = page.locator("#pivots li").first
        self.assertIn("Annex III use: Employment to none. Becomes Minimal risk", first.inner_text())
        first.get_by_role("button").click()
        self.assertIn("Minimal risk", page.inner_text("#tier"))
        self.assertEqual(page.input_value("#a-annex3"), "")
        self.assertEqual(page.input_value("#preset"), "")
        page.select_option("#preset", "transcript")
        self.assertIn("Profiles people: no to yes. Becomes High-risk", page.inner_text("#pivots"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_register_download_and_import(self):
        page = self.open()
        page.evaluate("window.localStorage.clear()")
        page.reload()
        page.click("#reg-csv")
        self.assertIn("nothing to download", page.inner_text("#reg-msg"))
        page.click("#reg-examples")
        with page.expect_download() as d:
            page.click("#reg-csv")
        self.assertEqual(d.value.suggested_filename, "ai-register.csv")
        self.assertEqual(pathlib.Path(d.value.path()).read_text(encoding="utf-8"),
                         (ROOT / "examples" / "register.csv").read_text(encoding="utf-8"))
        with page.expect_download() as d:
            page.click("#reg-json")
        saved = json.loads(pathlib.Path(d.value.path()).read_text(encoding="utf-8"))
        self.assertEqual(len(saved["systems"]), 9)
        page.once("dialog", lambda dlg: dlg.accept())
        page.click("#reg-clear")
        page.set_input_files("#reg-import", files=[{"name": "mine.json", "mimeType": "application/json",
                                                    "buffer": json.dumps(saved).encode("utf-8")}])
        page.wait_for_function("document.querySelectorAll('#register tbody tr').length === 9")
        self.assertIn("Imported 9 systems from mine.json.", page.inner_text("#reg-msg"))
        page.set_input_files("#reg-import", files=[{"name": "messy.csv", "mimeType": "text/csv",
                                                    "buffer": b"Name,role,profiling\nNew one,boss,maybe\n"}])
        page.wait_for_function("document.querySelectorAll('#register tbody tr').length === 10")
        msg = page.inner_text("#reg-msg")
        self.assertIn("Imported 1 system from messy.csv. Check: New one: profiling", msg)
        page.set_input_files("#reg-import", files=[{"name": "again.json", "mimeType": "application/json",
                                                    "buffer": json.dumps([{"name": "New one", "role": "Provider"}]).encode("utf-8")}])
        page.wait_for_function("document.getElementById('reg-msg').textContent.indexOf('again.json') > 0")
        msg = page.inner_text("#reg-msg")
        self.assertIn("1 system replaced one already in the register with the same name.", msg)
        self.assertIn('New one: role "Provider" is not one of', msg)
        self.assertEqual(page.locator("#register tbody tr").count(), 10)
        page.set_input_files("#reg-import", files=[{"name": "bad.csv", "mimeType": "text/csv", "buffer": b"title\nx\n"}])
        page.wait_for_function("document.getElementById('reg-msg').textContent.indexOf('Could not import') === 0")
        self.assertIn('it needs a "name" column', page.inner_text("#reg-msg"))
        self.assertEqual(page.locator("#register tbody tr").count(), 10)
        self.assertEqual(self.errors, [])
        page.close()

    def test_unnamed_systems_get_unique_names(self):
        page = self.open()
        page.evaluate("window.localStorage.clear()")
        page.reload()
        page.fill("#a-name", "")
        page.dispatch_event("#a-name", "input")
        for _ in range(2):
            page.click("#reg-add")
        page.locator("#register tbody tr").nth(0).get_by_role("button", name="Remove").click()
        page.click("#reg-add")
        names = page.eval_on_selector_all("#register tbody tr td:first-child", "cells => cells.map(c => c.textContent)")
        self.assertEqual(sorted(names), ["System 1", "System 2"], "a new unnamed system never overwrites another")
        page.close()

    def test_phone_bar_jumps_to_the_result(self):
        page = self.open(390, 844)
        page.evaluate("window.scrollTo(0, 0)")
        bar = page.locator("#jump")
        self.assertTrue(bar.is_visible())
        self.assertIn("High-risk", bar.inner_text())
        bar.click()
        page.wait_for_function("document.getElementById('jump').classList.contains('away')")
        self.assertEqual(self.errors, [])
        page.close()
        desk = self.open()
        self.assertFalse(desk.locator("#jump").is_visible())
        desk.close()

    def test_every_control_has_a_label(self):
        page = self.open()
        unlabelled = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, button')).filter(e =>
            !((e.labels && e.labels.length && e.labels[0].textContent.trim()) || e.getAttribute('aria-label') ||
              (e.tagName === 'BUTTON' && e.textContent.trim()))).map(e => e.id || e.name)""")
        self.assertEqual(unlabelled, [])
        page.close()

    def test_phone_width_has_no_horizontal_scroll(self):
        page = self.open(390, 844)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 390)
        page.close()


if __name__ == "__main__":
    unittest.main()
