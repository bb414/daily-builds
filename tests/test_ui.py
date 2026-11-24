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
        self.errors = []
        self.requests = []
        page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("request", lambda r: self.requests.append(r.url))
        page.goto(APP_URL)
        return page

    def take_test(self, page, key="1"):
        page.click("#start-btn")
        for _ in range(3):
            page.wait_for_selector("#screen-break:not([hidden])")
            page.click("#break-go")
            page.wait_for_selector("#screen-trial:not([hidden])")
            while page.is_visible("#screen-trial"):
                page.wait_for_timeout(450)
                page.keyboard.press(key)
                if page.is_visible("#checker-block"):
                    page.wait_for_timeout(360)
                    page.keyboard.press(key)
                if page.is_visible("#screen-break") or page.is_visible("#screen-results"):
                    break

    def test_full_run_by_keyboard(self):
        page = self.open()
        self.take_test(page, "1")
        page.wait_for_selector("#screen-results:not([hidden])")
        self.assertIn("Your results", page.inner_text("#results-title"))
        # Always answering "definitely a scam" gets exactly the scams right.
        tiles = page.locator(".tile-value").all_inner_texts()
        self.assertEqual([t.split()[0] for t in tiles], ["4", "6", "4"])
        self.assertEqual(page.locator(".review details").count(), 28)
        self.assertEqual(self.errors, [])
        self.assertTrue(all(u.startswith("file:") or u.startswith("blob:") or u.startswith("data:")
                            for u in self.requests), self.requests)
        page.close()

    def test_checker_panel_shows_verdict_and_reasons(self):
        page = self.open()
        page.click("#start-btn")
        page.click("#break-go")
        for _ in range(8):
            page.wait_for_timeout(450)
            page.keyboard.press("3")
        page.click("#break-go")
        page.wait_for_timeout(450)
        page.keyboard.press("2")
        page.wait_for_selector("#checker-block:not([hidden])")
        text = page.inner_text("#checker-panel")
        self.assertRegex(text, r"Likely (a scam|genuine)")
        self.assertRegex(text, r"\d+% sure")
        self.assertGreaterEqual(page.locator("#checker-panel li").count(), 1)
        self.assertTrue(page.locator("#answers-first .answer.chosen").count() == 1)
        self.assertEqual(self.errors, [])
        page.close()

    def test_demo_results_render_on_a_phone(self):
        page = self.open(390, 844)
        page.select_option("#demo-persona", "leaner")
        page.click("#demo-btn")
        page.wait_for_selector("#screen-results:not([hidden])")
        self.assertIn("Example", page.inner_text("#results"))
        width = page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390)
        self.assertEqual(self.errors, [])
        page.close()

    def answer_all(self, page):
        for _ in range(3):
            page.wait_for_selector("#screen-break:not([hidden])")
            page.click("#break-go")
            while page.is_visible("#screen-trial"):
                page.wait_for_timeout(450)
                page.keyboard.press("4")
                if page.is_visible("#checker-block"):
                    page.wait_for_timeout(360)
                    page.keyboard.press("4")
                if page.is_visible("#screen-break") or page.is_visible("#screen-results"):
                    break

    def test_study_mode_saves_sessions_and_moves_on(self):
        page = self.open()
        page.click("#settings summary")
        page.check("#opt-study")
        page.fill("#study-name", "ui-test")
        page.fill("#participant-id", "P007")
        page.select_option("#allocation", "control")
        page.uncheck("#opt-show-results")
        self.assertEqual(page.inner_text("#start-btn"), "Start for participant P007")
        page.click("#start-btn")
        self.answer_all(page)
        page.wait_for_selector("#screen-results:not([hidden])")
        self.assertIn("Thank you", page.inner_text("#results"))
        self.assertIn("1 session saved on this device", page.inner_text("#results"))
        stored = page.evaluate("JSON.parse(localStorage.getItem('crutch-check-sessions-v1'))")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["arm"], "control")
        self.assertEqual(stored[0]["participant"], "P007")
        self.assertTrue(all(t["checker"] is None for t in stored[0]["trials"]))
        page.click("[data-act=next]")
        self.assertEqual(page.input_value("#participant-id"), "P008")
        self.assertEqual(self.errors, [])
        page.evaluate("localStorage.clear()")
        page.close()

    def test_study_mode_needs_an_id(self):
        page = self.open()
        page.click("#settings summary")
        page.check("#opt-study")
        page.fill("#participant-id", "")
        page.click("#start-btn")
        self.assertTrue(page.is_visible("#start-error"))
        self.assertTrue(page.is_visible("#screen-intro"))
        page.close()

    def test_open_a_saved_bundle_and_pick_a_session(self):
        import json
        import tempfile
        from crutch_check.cohort import simulate_cohort
        from crutch_check.sessions import bundle
        sessions = simulate_cohort(2, "mixed", seed=1, study="ui")
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "bundle.json"
            good.write_text(json.dumps(bundle(sessions)))
            bad = Path(d) / "bad.json"
            bad.write_text('{"format": "something-else"}')
            page = self.open()
            page.set_input_files("#load-file", str(bad))
            page.wait_for_selector("#load-error:not([hidden])")
            self.assertIn("not a Crutch check session file", page.inner_text("#load-error"))
            page.set_input_files("#load-file", str(good))
            page.wait_for_selector("[data-pick]")
            self.assertEqual(page.locator("[data-pick]").count(), 4)
            self.assertTrue(page.is_hidden("#load-error"))
            page.click("[data-pick='1']")
            page.wait_for_selector("#screen-results:not([hidden])")
            self.assertIn("Saved session: " + sessions[1]["participant"], page.inner_text("#results"))
            self.assertEqual(self.errors, [])
            page.close()

    def test_resume_after_reload(self):
        page = self.open()
        page.click("#start-btn")
        page.click("#break-go")
        for _ in range(3):
            page.wait_for_timeout(450)
            page.keyboard.press("2")
        page.reload()
        page.wait_for_selector("#resume-banner:not([hidden])")
        self.assertIn("message 4 of 28", page.inner_text("#resume-banner"))
        page.click("#resume-btn")
        page.wait_for_selector("#screen-trial:not([hidden])")
        self.assertEqual(page.inner_text("#trial-count"), "Message 4 of 8")
        page.reload()
        page.click("#discard-btn")
        self.assertTrue(page.is_hidden("#resume-banner"))
        self.assertEqual(self.errors, [])
        page.close()

    def test_results_explain_strategies_instincts_and_cues(self):
        page = self.open()
        page.click("#demo-btn")
        text = page.inner_text("#results")
        for phrase in ("What if you had used it differently?", "Always follow the checker",
                       "Your instincts on your own", "What tripped you up"):
            self.assertIn(phrase, text)
        self.assertEqual(self.errors, [])
        page.close()

    def test_holding_a_key_answers_only_once(self):
        page = self.open()
        page.click("#start-btn")
        page.click("#break-go")
        page.wait_for_timeout(300)
        for _ in range(12):
            page.keyboard.down("3")
            page.wait_for_timeout(40)
        page.keyboard.up("3")
        page.wait_for_timeout(300)
        self.assertEqual(page.inner_text("#trial-count"), "Message 2 of 8")
        page.close()

    def test_resume_at_a_round_boundary_shows_the_instructions(self):
        page = self.open()
        page.click("#start-btn")
        page.click("#break-go")
        for _ in range(8):
            page.wait_for_timeout(420)
            page.keyboard.press("3")
        page.wait_for_selector("#screen-break:not([hidden])")
        page.reload()
        page.click("#resume-btn")
        page.wait_for_selector("#screen-break:not([hidden])")
        self.assertIn("round 2 of 3", page.inner_text("#break-card").lower())
        self.assertIn("second opinion", page.inner_text("#break-card"))
        page.close()

    def test_failed_saving_offers_a_download_and_listeners_are_not_duplicated(self):
        page = self.browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script("""
          window.__listeners = {};
          const add = EventTarget.prototype.addEventListener;
          EventTarget.prototype.addEventListener = function (type, fn, opts) {
            const key = (this.id || this.nodeName || 'window') + ':' + type;
            window.__listeners[key] = (window.__listeners[key] || 0) + 1;
            return add.call(this, type, fn, opts);
          };
          Storage.prototype.setItem = function () { throw new Error('quota'); };
        """)
        page.goto(APP_URL)
        page.click("#settings summary")
        page.check("#opt-study")
        page.uncheck("#opt-show-results")
        page.click("#start-btn")
        self.answer_all(page)
        page.wait_for_selector("#screen-results:not([hidden])")
        text = page.inner_text("#results")
        self.assertIn("could not be saved", text)
        self.assertTrue(page.is_visible("[data-act=json]"))
        page.click("[data-act=next]")
        page.click("#start-btn")
        self.answer_all(page)
        page.click("[data-act=next]")
        counts = page.evaluate("window.__listeners")
        self.assertEqual(counts.get("discard-btn:click"), 1)
        self.assertEqual(counts.get("bundle-list:click"), 1)
        self.assertEqual(errors, [])
        page.close()

    def test_unreadable_saved_sessions_are_not_overwritten(self):
        page = self.open()
        page.evaluate("localStorage.setItem('crutch-check-sessions-v1', '{broken')")
        page.reload()
        page.click("#settings summary")
        page.check("#opt-study")
        self.assertIn("could not be read", page.inner_text("#saved-panel"))
        self.assertIn("Some people get a second opinion", page.inner_text("#intro-lede"))
        page.uncheck("#opt-show-results")
        page.click("#start-btn")
        self.answer_all(page)
        page.wait_for_selector("#screen-results:not([hidden])")
        self.assertIn("could not be saved", page.inner_text("#results"))
        self.assertEqual(page.evaluate("localStorage.getItem('crutch-check-sessions-v1')"), "{broken")
        page.click("[data-act=next]")
        page.select_option("#allocation", "checker")
        self.assertIn("Halfway through, an AI checker", page.inner_text("#intro-lede"))
        page.evaluate("localStorage.clear()")
        page.close()

    def test_unfinished_comparison_session_is_described_correctly(self):
        import json
        import tempfile
        from crutch_check import model as M
        s = M.simulate_responses(M.build_session(5, "control"), M.PERSONAS["loner"], 1)
        for t in s["trials"][20:]:
            t["final"] = None
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "partial.json"
            f.write_text(json.dumps(s))
            page = self.open()
            page.set_input_files("#load-file", str(f))
            page.wait_for_selector("#screen-results:not([hidden])")
            text = page.inner_text("#results")
            self.assertIn("Round 2 without the checker", text)
            self.assertNotIn("How you used the checker", text)
            self.assertEqual(page.locator("text=Not answered").count(), 8)
            self.assertEqual(self.errors, [])
            page.close()

    def test_every_control_has_a_name(self):
        page = self.open()
        unnamed = page.evaluate("""() => [...document.querySelectorAll('button, select, input')]
            .filter(el => el.offsetParent !== null)
            .filter(el => {
              const label = el.labels && el.labels.length ? el.labels[0].textContent : '';
              return !(el.getAttribute('aria-label') || el.textContent.trim() || label.trim());
            }).map(el => el.outerHTML)""")
        self.assertEqual(unnamed, [])
        page.close()


if __name__ == "__main__":
    unittest.main()
