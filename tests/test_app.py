"""Drives the browser app in headless Chromium. Skipped if Playwright for Python is not installed."""

import unittest
from pathlib import Path

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None

APP = (Path(__file__).resolve().parent.parent / "app" / "index.html").as_uri()


@unittest.skipUnless(sync_playwright, "Playwright for Python is not installed")
class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover - no browser available
            cls.pw.stop()
            raise unittest.SkipTest(f"No Chromium available: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def open(self, width=1280, height=900, url=APP):
        page = self.browser.new_page(viewport={"width": width, "height": height})
        self.problems = []
        page.on("console", lambda m: self.problems.append(m.text) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: self.problems.append(str(e)))
        page.on("request", lambda r: self.problems.append("network: " + r.url)
                if not r.url.startswith(("file:", "data:", "blob:")) else None)
        page.goto(url)
        return page

    def test_opens_on_the_model_with_the_default_answer(self):
        page = self.open()
        self.assertFalse(page.is_hidden("#panel-model"))
        self.assertIn("88.9%", page.inner_text("#model-tiles"))
        self.assertEqual(page.locator("#error-table tbody tr").count(), 4)
        self.assertEqual(page.locator("#waffle .cell").count(), 100)
        self.assertIn("That makes 89 right", page.inner_text("#waffle-text"))
        self.assertEqual(self.problems, [])

    def test_sliders_work_from_the_keyboard(self):
        page = self.open()
        before = page.inner_text("#model-tiles")
        page.focus("#s-aiSignal")
        for _ in range(10):
            page.keyboard.press("ArrowLeft")
        self.assertNotEqual(page.inner_text("#model-tiles"), before)
        self.assertEqual(page.get_attribute("#s-aiSignal", "aria-valuetext"), "0.5 (weak)")
        self.assertEqual(self.problems, [])

    def test_choosing_a_rule_updates_the_closer_look(self):
        page = self.open()
        page.check("input[name=mapRule][value=fixed]", force=True)
        expect(page.locator("#waffle-text")).to_contain_text("defer at a fixed rate")
        self.assertIn("defer at a fixed rate", page.inner_text("#map-rule-hint"))
        self.assertIn("defer at a fixed rate", page.inner_text("#lever-rule"))
        self.assertIn("on 0% of this map", page.inner_text("#map-note"))
        self.assertEqual(page.locator("#waffle .cell").count(), 100)

    def test_presets_and_settings_link(self):
        page = self.open()
        page.select_option("#preset", label="Two equals with honest confidence")
        self.assertIn("Equally accurate", page.inner_text("#preset-hint"))
        self.assertEqual(page.input_value("#s-human"), "0.8")
        self.assertIn("93.5%", page.inner_text("#model-tiles"))
        url = page.url
        self.assertIn("#model?human=0.8&ai=0.8", url)
        self.assertIn("Biggest gains", page.inner_text("#lever-note"))
        problems = self.problems
        other = self.open(url=url)
        self.assertEqual(other.input_value("#s-humanSignal"), "2")
        self.assertIn("93.5%", other.inner_text("#model-tiles"))
        other.close()
        page.click("#tab-about")
        self.assertNotIn("#model?", page.url)
        self.assertEqual(problems + self.problems, [])

    def test_extreme_settings_stay_responsive(self):
        for params in ["human=0.99&ai=0.5&overlap=-1&aiSignal=4&humanSignal=4&aiBias=2&humanBias=-2&threshold=0.99&deferRate=1",
                       "human=0.5&ai=0.5&overlap=1&aiSignal=0&humanSignal=0&aiBias=-2&humanBias=2&threshold=0.5&deferRate=0"]:
            page = self.open(url=APP + "#model?" + params)
            ms = page.evaluate("""() => {
                const s = document.getElementById('s-aiSignal');
                const t0 = performance.now();
                for (let i = 0; i < 10; i++) { s.value = String(i * 0.4); s.dispatchEvent(new Event('input')); }
                return (performance.now() - t0) / 10;
            }""")
            self.assertLess(ms, 150, f"one redraw took {ms:.0f} ms")
            self.assertNotIn("NaN", page.inner_text("#panel-model"))
            self.assertEqual(page.locator("#waffle .cell").count(), 100)
            self.assertEqual(self.problems, [])
            page.close()

    def test_fits_a_phone(self):
        page = self.open(390, 844)
        width = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390)
        self.assertEqual(self.problems, [])

    def test_tabs_work_from_the_keyboard(self):
        page = self.open()
        page.focus("#tab-model")
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.get_attribute("#tab-about", "aria-selected"), "true")
        self.assertFalse(page.is_hidden("#panel-about"))
        self.assertTrue(page.is_hidden("#panel-model"))
        page.keyboard.press("Home")
        self.assertFalse(page.is_hidden("#panel-model"))


if __name__ == "__main__":
    unittest.main()
