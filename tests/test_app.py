"""Drive the browser app in headless Chromium: the sample, uploads, decisions, downloads, a frame and a phone.

Skipped cleanly when Playwright or its browser is not installed.
"""

import csv
import io
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app", "index.html")
DATA = os.path.join(ROOT, "data")
URL = "file://" + APP

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "Playwright for Python is not installed")
class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover - depends on the machine
            cls.pw.stop()
            raise unittest.SkipTest("Chromium could not start: %s" % exc)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def open(self, width=1280, height=900, url=URL):
        page = self.browser.new_page(viewport={"width": width, "height": height}, accept_downloads=True)
        self.errors, self.requests = [], []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        page.on("request", lambda r: self.requests.append(r.url) if not r.url.startswith(("file:", "data:", "blob:")) else None)
        page.goto(url)
        page.wait_for_selector(".reg")
        return page

    def tearDown(self):
        self.assertEqual(self.errors, [], "the page reported errors")
        self.assertEqual(self.requests, [], "the page tried to reach the network")

    def download(self, page, selector):
        with page.expect_download() as info:
            page.click(selector)
        path = os.path.join(self.tmp.name, info.value.suggested_filename)
        info.value.save_as(path)
        with open(path, encoding="utf-8-sig") as f:
            return info.value.suggested_filename, f.read()

    def test_opens_with_the_sample_worked_through(self):
        page = self.open()
        self.assertEqual(page.locator(".reg").count(), 22)
        meters = page.inner_text("#meters")
        self.assertIn("838", meters)
        self.assertIn("after you cancelled", meters)
        self.assertEqual(page.get_attribute("#tab-regulars", "aria-selected"), "true")
        self.assertIn("£839", page.text_content("#gauge-readout"))
        page.close()

    def test_tabs_work_with_the_keyboard(self):
        page = self.open()
        page.focus("#tab-regulars")
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.get_attribute("#tab-calendar", "aria-selected"), "true")
        self.assertTrue(page.is_visible("#view-calendar"))
        page.keyboard.press("End")
        self.assertEqual(page.get_attribute("#tab-how", "aria-selected"), "true")
        page.close()

    def test_messy_upload_lists_skipped_rows_and_a_bad_file_gets_a_message(self):
        page = self.open()
        page.set_input_files("#file-input", [os.path.join(DATA, "messy-export.csv")])
        page.wait_for_selector(".file-card")
        self.assertEqual(page.locator(".file-card").count(), 1)
        body = page.inner_text("#statements-body")
        self.assertIn("5 rows not used", body)
        page.click(".skips summary")
        self.assertIn('Could not read the date "TBC"', page.inner_text(".skips"))
        bad = os.path.join(self.tmp.name, "statement.pdf.csv")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("%PDF-1.7 not really a statement")
        page.set_input_files("#file-input", [bad])
        page.wait_for_function("document.querySelectorAll('.file-card').length === 2")
        self.assertIn("This is a PDF", page.inner_text("#statements-body"))
        page.close()

    def test_choosing_columns_by_hand(self):
        page = self.open()
        odd = os.path.join(self.tmp.name, "odd.csv")
        with open(odd, "w", encoding="utf-8") as f:
            f.write("When,Who,How much\n")
            for m in range(1, 7):
                f.write("%02d/%02d/2026,PLANET GYM,-20.00\n" % (5, m))
        page.set_input_files("#file-input", [odd])
        page.wait_for_selector(".file-card")
        page.click("[data-action=map]")
        page.select_option("[data-map-role=date]", "0")
        page.select_option("[data-map-role=payee]", "1")
        page.select_option("[data-map-role=amount]", "2")
        page.fill("[data-map-header]", "1")
        page.click("[data-action=apply-map]")
        page.wait_for_function("document.querySelector('#statements-body').innerText.includes('6 payments read') || document.querySelector('#statements-body').innerText.includes('6\\npayments read')")
        page.click("#tab-regulars")
        self.assertIn("Planet Gym", page.inner_text("#regulars-body"))
        page.close()

    def test_decide_then_take_everything_away(self):
        page = self.open()
        card = page.locator(".reg", has_text="Tidyup Cleaning")
        card.locator("text=Cancel").click()
        page.click("#tab-plan")
        plan = page.inner_text("#plan-body")
        self.assertIn("Tidyup Cleaning", plan)
        self.assertIn("Since your last review", plan)
        name, text = self.download(page, "[data-action=register]")
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 22)
        self.assertEqual([r["Decision"] for r in rows if r["Name"] == "Tidyup Cleaning"], ["Cancel"])
        name, text = self.download(page, "[data-action=budget]")
        self.assertEqual(len(list(csv.reader(io.StringIO(text)))[0]), 14)
        name, ics = self.download(page, "#plan-body [data-action=ics]")
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR"))
        self.assertIn("Cancel Tidyup Cleaning before", ics.replace("\r\n ", ""))
        name, review = self.download(page, "[data-action=save-review]")
        saved = os.path.join(self.tmp.name, name)
        self.assertEqual(json.loads(review)["format"], "still-paying-review")
        # Reopen the saved review in a fresh page: decisions come back and the banner offers this month's export.
        page2 = self.open()
        page2.set_input_files("#review-input", saved)
        page2.wait_for_selector("#banner:not([hidden])")
        self.assertIn("Reopened your review", page2.inner_text("#banner"))
        page2.click("#tab-regulars")
        checked = page2.locator(".reg", has_text="Tidyup Cleaning").locator("input[value=cancel]")
        self.assertTrue(checked.is_checked())
        page2.close()
        page.close()

    def test_runway_answers_will_the_money_last(self):
        page = self.open()
        page.click("#tab-calendar")
        self.assertEqual(page.input_value("#rw-balance"), "544.99")
        self.assertIn("Goes past your £1,000.00 overdraft", page.inner_text(".runway-verdict"))
        self.assertEqual(page.locator(".rw-col").count(), 60)
        page.fill("#rw-balance", "3000")
        page.press("#rw-balance", "Tab")
        page.wait_for_function("document.querySelector('.runway-verdict').innerText.includes('Stays in credit')")
        page.fill("#rw-x-amount", "250")
        page.fill("#rw-x-name", "Birthday money")
        page.click("[data-action=rw-add]")
        self.assertIn("Birthday money", page.inner_text("#runway"))
        page.close()

    def test_works_inside_a_frame(self):
        host = os.path.join(self.tmp.name, "host.html")
        with open(host, "w", encoding="utf-8") as f:
            f.write('<!doctype html><title>Host</title><iframe id="app" src="%s" style="width:1100px;height:800px"></iframe>' % URL)
        page = self.browser.new_page(viewport={"width": 1200, "height": 900}, accept_downloads=True)
        self.errors, self.requests = [], []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.goto("file://" + host)
        frame = page.frame_locator("#app")
        frame.locator(".reg").first.wait_for()
        frame.locator("#tab-calendar").click()
        self.assertTrue(frame.locator(".cal-grid").first.is_visible())
        frame.locator("#tab-statements").click()
        frame.locator("#file-input").set_input_files(os.path.join(DATA, "credit-card.csv"))
        frame.locator(".file-card").first.wait_for()
        with page.expect_download() as info:
            frame.locator("[data-action=download-template]").click()
        self.assertEqual(info.value.suggested_filename, "still-paying-template.csv")
        page.close()

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(width=390, height=844)
        for view in ["statements", "regulars", "calendar", "plan", "how"]:
            page.click("#tab-" + view)
            width = page.evaluate("document.documentElement.scrollWidth")
            self.assertLessEqual(width, 390, view)
        page.close()

    def test_every_control_has_a_name(self):
        page = self.open()
        for view in ["statements", "regulars", "calendar", "plan"]:
            page.click("#tab-" + view)
            missing = page.evaluate("""() => Array.from(document.querySelectorAll('input, select, textarea, button'))
              .filter(el => el.offsetParent !== null && el.type !== 'hidden')
              .filter(el => !(el.labels && el.labels.length) && !el.getAttribute('aria-label') && !(el.textContent || '').trim() && !el.closest('label'))
              .map(el => el.outerHTML.slice(0, 80))""")
            self.assertEqual(missing, [], view)
        page.close()


if __name__ == "__main__":
    unittest.main()
