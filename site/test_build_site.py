"""Tests for the site builder. Run from the repository root:

    python -m unittest discover -s site -p "test_*.py"

The full-build test needs the build branches fetched and is skipped otherwise.
"""

import html
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import build_site as B  # noqa: E402

CONFIG = B.load_config()


class Table(unittest.TestCase):
    def test_reads_rows_below_the_separator(self):
        readme = "\n".join([
            "intro",
            "| Date | Project | What it does | Theme | Stack | Branch |",
            "|------|---------|--------------|-------|-------|--------|",
            "| 2026-12-01 | One | Does one thing | Markets and trading | Offline HTML/JavaScript app | [build/2026-12-01-one](https://x) |",
            "| 2026-11-30 | Two | Does two things | Innovation management | Offline HTML/JavaScript app | [build/2026-11-30-two](https://x) |",
            "",
            "after the table",
        ])
        rows = B.parse_table(readme)
        self.assertEqual([r["branch"] for r in rows], ["build/2026-12-01-one", "build/2026-11-30-two"])
        self.assertEqual(rows[0]["theme"], "Markets and trading")

    def test_the_real_index_parses(self):
        with open(os.path.join(B.ROOT, "README.md"), encoding="utf-8") as f:
            rows = B.parse_table(f.read())
        self.assertGreater(len(rows), 10)
        self.assertTrue(all(r["branch"].startswith("build/") for r in rows))
        self.assertTrue(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]) for r in rows))


class Categories(unittest.TestCase):
    def test_every_brief_theme_has_a_category(self):
        cases = {
            "AI adoption and scaling beyond the pilot": "ai-adoption",
            "Human-AI interaction and over-reliance on AI": "human-ai",
            "AI in consumer fintech and digital financial literacy": "fintech",
            "Innovation management": "innovation",
            "AI governance and regulation (EU AI Act, UK approach)": "governance",
            "Consulting toolkits (market sizing)": "consulting",
            "Markets and trading: options basics": "markets",
            "Retail operations and forecasting": "retail",
            "Sustainability and carbon: green forecasting": "sustainability",
            "Explainable AI and decision-making tools": "explainable-ai",
            "Sales operations and CRM analytics": "sales",
            "Team and sports leadership": "sport",
            "Language learning (Czech)": "languages",
            "Minecraft tools": "fun",
            "Something new entirely": "other",
        }
        for theme, want in cases.items():
            self.assertEqual(B.categorise(theme, "build/x", CONFIG), want, theme)

    def test_overrides_win(self):
        cfg = dict(CONFIG, categoryOverrides={"build/x": "markets"})
        self.assertEqual(B.categorise("Innovation management", "build/x", cfg), "markets")


class Taglines(unittest.TestCase):
    def test_bold_question(self):
        self.assertEqual(B.tagline("# T\n\n**Why does it stall?**\n\nMore.", "what"), "Why does it stall?")

    def test_disclaimer_is_skipped(self):
        text = "# T\n\n**Simplified and illustrative. Not legal advice.** Some caveat.\n\n**How much is enough?**\n"
        self.assertEqual(B.tagline(text, "what"), "How much is enough?")
        text = "# T\n\n**Not legal advice.** Caveat text here.\n\nWhere does a system sit under the Act, and what follows? More.\n"
        self.assertEqual(B.tagline(text, "what"), "Where does a system sit under the Act, and what follows?")

    def test_lead_bold_sentence_and_fallbacks(self):
        self.assertEqual(B.tagline("# T\n\n**Counterfactual explanations for a model.** Then more.", "w"), "Counterfactual explanations for a model.")
        self.assertEqual(B.tagline("", "A plain summary of the project"), "A plain summary of the project")
        self.assertEqual(B.tagline("# T\n\n**Q?**", "w", override="Mine"), "Mine")
        self.assertTrue(B.tagline("", "word " * 80).endswith("…"))


class Markdown(unittest.TestCase):
    def test_links_that_would_break_become_text(self):
        text = ("# Title\n\n**Hook?**\n\nSee [the app](app/index.html), [a report](examples/r.html), [the code](pkg/), "
                "[the brief](https://github.com/bb414/daily-builds/blob/main/BRIEF.md), [findings](FINDINGS.md#results) "
                "and [docs](https://docs.example.org).\n\n![shot](docs/a.png) ![gone](docs/missing.png)\n")
        out = B.render_markdown(text, {"app/index.html", "docs/a.png"}, {"README.md": "index.html", "FINDINGS.md": "findings.html"}, "Hook?")
        self.assertNotIn("<h1>", out)
        self.assertNotIn("Hook?", out)
        self.assertIn('href="app/index.html"', out)
        self.assertIn('href="findings.html#results"', out)
        self.assertIn('href="https://docs.example.org" target="_blank" rel="noopener"', out)
        self.assertNotIn("github.com/bb414", out)
        self.assertNotIn('href="pkg/"', out)
        self.assertIn('<span class="was-link">a report</span>', out)
        self.assertIn('src="docs/a.png"', out)
        self.assertNotIn("missing.png", out)


def have_build_branches():
    try:
        out = subprocess.run(["git", "branch", "-r", "--list", "origin/build/*"], cwd=B.ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    return bool(out.strip())


@unittest.skipUnless(have_build_branches(), "fetch the build branches to run the full build")
class FullBuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = os.path.join(cls.tmp.name, "site")
        cls.projects, cls.skipped = B.build(cls.out, CONFIG)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def pages(self):
        for folder, _dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith(".html") and "/app/" not in os.path.join(folder, name).replace(os.sep, "/") and "/examples/" not in folder.replace(os.sep, "/"):
                    yield os.path.join(folder, name)

    def test_every_project_in_the_index_has_a_page_and_an_app(self):
        self.assertEqual(self.skipped, [])
        for p in self.projects:
            self.assertTrue(os.path.exists(os.path.join(self.out, p["url"])), p["slug"])
            self.assertTrue(p["app"], p["slug"])

    def test_every_project_page_embeds_its_app_and_has_tabs(self):
        for p in self.projects:
            with open(os.path.join(self.out, p["url"]), encoding="utf-8") as f:
                text = f.read()
            self.assertRegex(text, r'<iframe src="app/index\.html" title="[^"]+: the interactive app"', p["slug"])
            self.assertIn('id="tab-try"', text)
            self.assertIn('id="tab-how"', text)
            self.assertIn("static/project.js", text)

    def test_every_internal_link_and_image_resolves(self):
        for page in self.pages():
            with open(page, encoding="utf-8") as f:
                text = f.read()
            for attr, target in re.findall(r'(href|src)="([^"]+)"', text):
                target = html.unescape(target)
                if target.startswith(("#", "mailto:")) or re.match(r"https?://", target):
                    continue
                path = target.split("#", 1)[0].split("?", 1)[0]
                full = os.path.normpath(os.path.join(os.path.dirname(page), path))
                self.assertTrue(os.path.exists(full), "%s: %s %s" % (os.path.relpath(page, self.out), attr, target))

    def test_no_source_code_or_private_links_are_published(self):
        for folder, _dirs, files in os.walk(self.out):
            for name in files:
                self.assertFalse(name.endswith((".py", ".R", ".ipynb")), os.path.join(folder, name))
        for page in self.pages():
            with open(page, encoding="utf-8") as f:
                text = f.read()
            rel = os.path.relpath(page, self.out)
            # The repository is private, so no link may point into it.
            self.assertIsNone(re.search(r'href="https?://github\.com/bb414/daily-builds', text), rel)
            self.assertNotIn("\u2014", text, rel)

    def test_index_data_matches_the_pages(self):
        with open(os.path.join(self.out, "projects.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["projects"]), len(self.projects))
        dates = [p["date"] for p in data["projects"]]
        self.assertEqual(dates, sorted(dates, reverse=True))


if __name__ == "__main__":
    unittest.main()
