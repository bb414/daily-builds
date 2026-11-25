"""Housekeeping: the two copies of the data match, the app stays offline, and the wording rules hold."""

import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP = os.path.join(ROOT, "app", "index.html")
DASH = chr(0x2014)  # the em dash, written as a code point so this file never contains one
BANNED = [bytes.fromhex(h).decode() for h in ("436c61756465", "416e7468726f706963")]
SKIP_DIRS = {".git", "__pycache__", "node_modules"}
TEXT_EXT = {".py", ".js", ".html", ".md", ".json", ".txt", ".csv", ".cfg", ".toml"}


def repo_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            yield os.path.join(base, name)


class RepoTest(unittest.TestCase):
    def setUp(self):
        with open(APP, encoding="utf-8") as fh:
            self.html = fh.read()

    def test_data_block_matches_data_json(self):
        start = self.html.index("/* DATA START */")
        end = self.html.index("/* DATA END */")
        block = self.html[start:end]
        literal = block[block.index("{"):block.rindex("}") + 1]
        with open(os.path.join(ROOT, "mislabelled", "data.json"), encoding="utf-8") as fh:
            self.assertEqual(json.loads(literal), json.load(fh))

    def test_model_block_exports_itself(self):
        model = self.html[self.html.index("/* MODEL START */"):self.html.index("/* MODEL END */")]
        self.assertIn("module.exports", model)

    def test_app_makes_no_network_requests(self):
        urls = re.findall(r"https?://[^\s\"'<>)]+", self.html)
        self.assertEqual([u for u in urls if u != "http://www.w3.org/2000/svg"], [])
        for pattern in ("fetch(", "XMLHttpRequest", "<link ", "import(", "src=\"http"):
            self.assertNotIn(pattern, self.html)

    def test_wording_rules(self):
        for path in repo_files():
            if os.path.splitext(path)[1].lower() not in TEXT_EXT:
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            rel = os.path.relpath(path, ROOT)
            self.assertNotIn(DASH, text, rel)
            for word in BANNED:
                self.assertNotIn(word.lower(), text.lower(), rel)


if __name__ == "__main__":
    unittest.main()
