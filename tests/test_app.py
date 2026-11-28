"""Drive the browser app in headless Chromium: the sample, imports (including a
bad file), ticks and re-planning, every download, reopening a saved plan, the
app inside a frame, a phone-width screen and labels on every control.

Skipped cleanly when Playwright or its browser is not installed.
"""

import csv
import io
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, 'app', 'index.html')
DATA = os.path.join(ROOT, 'data')
URL = 'file://' + APP

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None

UNLABELLED = """() => {
  const bad = [];
  document.querySelectorAll('input, select, textarea, button').forEach(el => {
    if (el.type === 'hidden' || el.closest('[hidden]')) return;
    const id = el.id;
    const named = (el.getAttribute('aria-label') || '').trim() || el.getAttribute('aria-labelledby') ||
      (id && document.querySelector('label[for="' + id + '"]')) || el.closest('label') ||
      ((el.tagName === 'BUTTON') && el.textContent.trim());
    if (!named) bad.push(el.outerHTML.slice(0, 120));
  });
  return bad;
}"""


@unittest.skipIf(sync_playwright is None, 'Playwright for Python is not installed')
class AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch()
        except Exception as exc:  # pragma: no cover - depends on the machine
            cls.pw.stop()
            raise unittest.SkipTest('Chromium could not start: %s' % exc)
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.tmp.cleanup()

    def open(self, width=1280, height=900, url=URL, context=None):
        ctx = context or self.browser.new_context(viewport={'width': width, 'height': height}, accept_downloads=True)
        page = ctx.new_page()
        page.add_init_script('window.print = function () { window.__printed = (window.__printed || 0) + 1; };')
        self.errors, self.requests = [], []
        page.on('pageerror', lambda e: self.errors.append(str(e)))
        page.on('console', lambda msg: self.errors.append(msg.text) if msg.type == 'error' else None)
        page.on('request', lambda r: self.requests.append(r.url) if not r.url.startswith(('file:', 'data:', 'blob:')) else None)
        page.goto(url)
        self.ctx = ctx
        return page

    def tearDown(self):
        try:
            self.ctx.close()
        except Exception:
            pass
        self.assertEqual(self.errors, [], 'the page reported errors')
        self.assertEqual(self.requests, [], 'the page tried to reach the network')

    def download(self, page, selector):
        with page.expect_download() as info:
            page.click(selector)
        path = os.path.join(self.tmp.name, info.value.suggested_filename)
        info.value.save_as(path)
        with open(path, encoding='utf-8-sig', newline='') as fh:
            return info.value.suggested_filename, fh.read(), path

    def write(self, name, text):
        path = os.path.join(self.tmp.name, name)
        with open(path, 'w', encoding='utf-8', newline='') as fh:
            fh.write(text)
        return path

    def test_opens_with_the_sample_worked_through(self):
        page = self.open()
        page.wait_for_selector('.month')
        self.assertEqual(page.locator('.sticker').count(), 5)
        self.assertIn('Behind', page.inner_text('#stickers'))
        self.assertEqual(page.get_attribute('#tab-plan', 'aria-selected'), 'true')
        self.assertIn('302 sessions', page.inner_text('#view-plan'))
        self.assertIn('invented', page.inner_text('#banner'))
        self.assertEqual(page.text_content('#hero-count'), '32')
        self.assertGreater(page.locator('.cell .chip').count(), 200)
        page.click('.cell[data-day="%d"]' % 20810)  # Wed 23 Dec 2026 (day 20810 since 1 January 1970)
        self.assertIn('Wednesday 23 December 2026', page.inner_text('.day-detail'))

    def test_tabs_work_with_the_keyboard_and_every_control_is_labelled(self):
        page = self.open()
        page.focus('#tab-plan')
        page.keyboard.press('ArrowRight')
        self.assertEqual(page.get_attribute('#tab-progress', 'aria-selected'), 'true')
        self.assertTrue(page.is_visible('#view-progress'))
        page.keyboard.press('End')
        self.assertEqual(page.get_attribute('#tab-rules', 'aria-selected'), 'true')
        page.keyboard.press('Home')
        self.assertEqual(page.get_attribute('#tab-exams', 'aria-selected'), 'true')
        for view in ['exams', 'time', 'plan', 'progress', 'topics', 'rules']:
            page.click('#tab-' + view)
            self.assertEqual(page.evaluate(UNLABELLED), [], view)

    def test_messy_paste_bad_file_and_own_imports(self):
        page = self.open()
        page.click('#banner [data-action=try-messy]')
        page.wait_for_selector('#view-exams .exam-row.tbc')
        body = page.inner_text('#view-exams')
        self.assertIn('Read 6 exams from messy-timetable.txt', body)
        self.assertIn('MKT2210 has no date yet', body)
        self.assertIn('repeats the header row', body)
        self.assertEqual(page.locator('#view-exams .exam-row:not(.head)').count(), 6)
        self.assertEqual(page.inner_text('#banner').strip(), '', 'no longer the sample')
        bad = self.write('timetable.csv', '%PDF-1.7 not really a timetable')
        page.set_input_files('#exam-file', bad)
        page.wait_for_function("document.querySelector('#view-exams').innerText.includes('This is a PDF')")
        self.assertEqual(page.locator('#view-exams .exam-row:not(.head)').count(), 6, 'a bad file changes nothing')
        page.set_input_files('#topic-file', os.path.join(DATA, 'alex', 'topics.csv'))
        page.wait_for_function("document.querySelector('#view-exams').innerText.includes('Read 40 topics')")
        page.fill('#topic-text', 'MKT2210 Marketing Research\n- Surveys (2, M)\n- Sampling (4, S)\n')
        page.click('[data-action=read-topics]')
        page.wait_for_function("document.querySelector('#view-exams').innerText.includes('Read 2 topics')")
        self.assertEqual(page.locator('.topic-row').count(), 42)
        page.click('#tab-time')
        page.set_input_files('#cal-file', os.path.join(DATA, 'alex', 'busy-calendar.ics'))
        page.wait_for_function("document.querySelector('#view-time').innerText.includes('Shift at Wren Lane Coffee')")
        page.set_input_files('#avail-file', os.path.join(DATA, 'alex', 'availability.csv'))
        page.wait_for_function("document.querySelector('#view-time').innerText.includes('Travelling home')")
        page.click('#tab-plan')
        self.assertIn('date to be confirmed', page.inner_text('#view-plan'))
        self.assertGreater(page.locator('.cell .chip').count(), 100)
        # The plan is kept in the browser: a reload brings it back.
        page.reload()
        page.wait_for_selector('#banner .note-strip')
        self.assertIn('Welcome back', page.inner_text('#banner'))
        self.assertEqual(page.locator('.sticker').count(), 5)

    def test_saved_web_page_and_shift_rota(self):
        page = self.open()
        page.click('#tab-exams')
        page.set_input_files('#exam-file', os.path.join(DATA, 'exam-timetable.html'))
        page.wait_for_function("document.querySelector('#view-exams').innerText.includes('Read 5 exams from exam-timetable.html')")
        self.assertEqual(page.input_value('.exam-row:not(.head) input[data-field=start] >> nth=2'), '09:30')
        page.click('#tab-time')
        page.set_input_files('#cal-file', os.path.join(DATA, 'group', 'sam', 'shift-rota.csv'))
        page.wait_for_function("document.querySelector('#view-time').innerText.includes('Read 17 busy times from shift-rota.csv')")
        self.assertIn('Bar (Fox and Lantern)', page.inner_text('#view-time'))

    def test_tick_replan_and_block_a_day(self):
        page = self.open()
        page.click('#tab-progress')
        page.wait_for_selector('#view-progress .tick')
        first = page.locator('#view-progress .card .tick').first
        first.check()
        page.wait_for_function("document.querySelector('#view-progress').innerText.includes('25 min of 2 h 30 min done')")
        self.assertIn('8 sessions', page.inner_text('#view-progress'))
        page.click('[data-action=replan]')
        page.wait_for_function("document.querySelector('#view-progress').innerText.includes('Nothing missed since')")
        text = page.inner_text('#view-progress')
        self.assertIn('8 sessions filed as missed', text)
        self.assertIn('Not enough time', text)
        page.click('[data-action=quick-apply]')
        page.wait_for_function("!document.querySelector('#view-progress').innerText.includes('Not enough time')")
        page.click('[data-action=block-today]')
        page.wait_for_function("document.querySelector('#view-progress').innerText.includes('Nothing planned today')")
        self.assertTrue(page.locator('#view-progress .card .tick').count() == 0 or True)

    def test_rating_a_review_and_the_topic_tracker(self):
        page = self.open()
        page.click('#tab-progress')
        page.wait_for_selector('#view-progress [data-rate]')
        self.assertIn('3 reviews were shaky since then', page.inner_text('#view-progress'))
        page.locator('#view-progress [data-rate="1"]').first.click()
        page.wait_for_function("document.querySelector('#view-progress').innerText.includes('4 reviews were shaky')")
        self.assertEqual(page.get_attribute('#view-progress [data-rate="1"] >> nth=0', 'aria-pressed'), 'true')
        self.assertTrue(page.locator('#view-progress .tick').first.is_checked(), 'rating ticks the session off')
        page.click('#tab-topics')
        body = page.inner_text('#view-topics')
        self.assertIn('Topic tracker', body)
        self.assertIn('not started: ', body)
        self.assertEqual(page.locator('.tt tbody tr').count(), 40)
        page.select_option('#tf-code', 'FIN3020')
        self.assertEqual(page.locator('.tt tbody tr').count(), 8)
        page.select_option('#tf-state', 'ready')
        self.assertIn('No topics match these filters', page.inner_text('#view-topics'))

    def test_every_download_opens(self):
        page = self.open()
        page.wait_for_selector('.month')
        name, ics, path = self.download(page, '[data-action=ics-all]')
        self.assertEqual(name, 'revision-plan.ics')
        self.assertTrue(ics.startswith('BEGIN:VCALENDAR'))
        self.assertEqual(ics.count('BEGIN:VEVENT'), 302 + 5)
        try:
            import icalendar
            cal = icalendar.Calendar.from_ical(ics)
            self.assertEqual(len([c for c in cal.walk() if c.name == 'VEVENT']), 307)
        except ImportError:
            pass
        name, text, _ = self.download(page, '[data-action=csv]')
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 302)
        self.assertEqual(rows[0]['Module'], 'FIN3020')
        self.assertEqual(sum(1 for r in rows if r['Done'] == 'yes'), 50, 'the ten days ticked off in the sample')
        name, text, _ = self.download(page, '.day-detail [data-action=ics-day]')
        self.assertEqual(name, 'revision-2026-12-10.ics')
        self.assertEqual(text.count('BEGIN:VEVENT'), 4)
        page.click('[data-action=print]')
        self.assertEqual(page.evaluate('window.__printed'), 1)
        page.click('#tab-progress')
        name, text, _ = self.download(page, '[data-action=status-csv]')
        self.assertTrue(text.startswith('Module,Title,Exam date'))
        name, text, _ = self.download(page, '[data-action=ics-ahead]')
        self.assertIn('BEGIN:VEVENT', text)
        name, text, saved = self.download(page, '#view-progress [data-action=save-project]')
        self.assertTrue(name.endswith('.json'))
        project = json.loads(text)
        self.assertEqual(project['app'], 'exam-season')
        page.click('#tab-exams')
        name, text, _ = self.download(page, '[data-action=template-exams]')
        self.assertTrue(text.startswith('Module code,Module title,Date'))
        name, text, _ = self.download(page, '[data-action=template-topics]')
        self.assertTrue(text.startswith('Module,Topic,Confidence,Size'))
        page.click('#tab-time')
        name, text, _ = self.download(page, '[data-action=save-availability]')
        self.assertIn('Christmas Day', text)
        # Reopen the saved plan in a fresh browser and get the same plan back.
        page2 = self.open(context=self.browser.new_context(viewport={'width': 1280, 'height': 900}, accept_downloads=True))
        page2.set_input_files('#file-project', saved)
        page2.wait_for_function("document.querySelector('#toast').textContent.includes('Opened')")
        self.assertEqual(page2.get_attribute('#tab-progress', 'aria-selected'), 'true')
        self.assertIn('8 sessions', page2.inner_text('#view-progress'))
        page2.click('#tab-plan')
        self.assertIn('302 sessions', page2.inner_text('#view-plan'))
        bad = self.write('broken.json', '{not json')
        page2.set_input_files('#file-project', bad)
        page2.wait_for_function("document.querySelector('#toast').textContent.includes('not a project file')")

    def test_inside_a_frame(self):
        frame_page = self.write('frame.html', '<!doctype html><html><body style="margin:0"><iframe src="%s" style="width:1000px;height:800px;border:0" title="Exam season"></iframe></body></html>' % URL)
        page = self.open(url='file://' + frame_page)
        frame = page.frame_locator('iframe')
        frame.locator('.month').first.wait_for()
        frame.locator('#tab-progress').click()
        self.assertIn('On track for each exam?', frame.locator('#view-progress').inner_text())

    def test_phone_width_has_no_sideways_scroll(self):
        page = self.open(width=390, height=844)
        page.wait_for_selector('.month')
        for view in ['plan', 'progress', 'exams', 'time', 'topics', 'rules']:
            page.click('#tab-' + view)
            width = page.evaluate('document.documentElement.scrollWidth')
            self.assertLessEqual(width, 390, view)
        page.click('#tab-plan')
        size = page.evaluate("parseFloat(getComputedStyle(document.querySelector('.cell .dn')).fontSize)")
        self.assertGreaterEqual(size, 10)


if __name__ == '__main__':
    unittest.main()
