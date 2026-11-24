"""Checks on the repository itself: style rules, README links and offline use."""

import os
import re
import unittest

from helpers import ROOT

TEXT = (".py", ".cjs", ".html", ".md", ".txt", ".csv", ".gitignore")


def text_files():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if name.endswith(TEXT):
                yield os.path.join(folder, name)


class HygieneTests(unittest.TestCase):
    def test_no_em_dashes(self):
        for path in text_files():
            with open(path, encoding="utf-8") as f:
                self.assertNotIn("\u2014", f.read(), os.path.relpath(path, ROOT) + " contains an em dash")

    def test_readme_links_exist(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as f:
            readme = f.read()
        targets = re.findall(r"\]\(([^)#]+)\)", readme) + re.findall(r"`((?:app|docs|examples|tests|stairstep)/[^`*<> ]+)`", readme)
        self.assertGreater(len(targets), 3)
        for target in targets:
            if not target.startswith("http"):
                self.assertTrue(os.path.exists(os.path.join(ROOT, target)), "README points to a missing file: " + target)

    def test_nothing_online(self):
        for rel in ("app/index.html", "stairstep/report.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
                self.assertIsNone(re.search(r"https?://|<link[^>]+href=", f.read()), rel)


if __name__ == "__main__":
    unittest.main()
