"""Checks on the repository itself: style rules, links in the README, and offline use."""

import os
import re
import unittest

from helpers import ROOT

TEXT_EXTENSIONS = (".py", ".cjs", ".html", ".md", ".txt", ".json", ".gitignore")


def text_files():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if name.endswith(TEXT_EXTENSIONS):
                yield os.path.join(folder, name)


class HygieneTests(unittest.TestCase):
    def test_no_em_dashes_anywhere(self):
        for path in text_files():
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("—", f.read(), "%s contains an em dash" % os.path.relpath(path, ROOT))

    def test_readme_links_point_to_real_files(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        targets = re.findall(r"\]\(([^)#]+)\)", readme) + re.findall(r"`((?:app|docs|examples|tests|second_opinion)/[^`*<> ]+)`", readme)
        self.assertGreater(len(targets), 5)
        for target in targets:
            if target.startswith("http"):
                continue
            self.assertTrue(os.path.exists(os.path.join(ROOT, target)), "README points to a missing file: " + target)

    def test_app_and_reports_make_no_network_requests(self):
        for rel in ("app/index.html", "second_opinion/report.py", "examples/cohort-report.html"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                text = f.read()
            self.assertIsNone(re.search(r"https?://|//cdn|<link[^>]+href=", text), rel + " refers to something online")


if __name__ == "__main__":
    unittest.main()
