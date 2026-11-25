"""Checks on the repository itself: links, wording and offline-only assets."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {".py", ".js", ".html", ".md", ".txt", ".json", ".csv", ""}


def text_files():
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or "__pycache__" in path.parts or not path.is_file():
            continue
        if path.suffix in TEXT_SUFFIXES:
            yield path


class TestRepo(unittest.TestCase):
    def test_readme_links_point_at_real_files(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        links = re.findall(r"\]\(([^)#]+)\)", readme)
        local = [link for link in links if not link.startswith(("http://", "https://"))]
        self.assertTrue(local)
        for link in local:
            self.assertTrue((ROOT / link).exists(), link)

    def test_no_em_dashes_anywhere(self):
        for path in text_files():
            self.assertNotIn("\u2014", path.read_text(encoding="utf-8"), str(path))

    def test_app_makes_no_external_requests(self):
        html = (ROOT / "app" / "index.html").read_text(encoding="utf-8")
        self.assertNotRegex(html, r"https?://")
        self.assertNotRegex(html, r"<script[^>]+src=")
        self.assertNotRegex(html, r"<link[^>]+href=")
        self.assertEqual(html.count("/* MODEL START */"), 1)
        self.assertEqual(html.count("/* MODEL END */"), 1)


if __name__ == "__main__":
    unittest.main()
