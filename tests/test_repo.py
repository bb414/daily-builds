"""Checks on the repository itself: the built app is current and the text is clean."""

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT = ('.py', '.js', '.html', '.css', '.md', '.csv', '.txt', '.ics', '.json', '.gitignore')


def text_files():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', 'node_modules')]
        for name in files:
            if name.endswith(TEXT):
                yield os.path.join(folder, name)


class RepoTest(unittest.TestCase):
    def test_built_app_is_current(self):
        proc = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'build_app.py'), '--check'], capture_output=True, encoding='utf-8')
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_no_long_dashes_or_assistant_names(self):
        banned = [chr(0x2014), 'Clau' + 'de', 'Anthro' + 'pic']
        for path in text_files():
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            for word in banned:
                self.assertNotIn(word, text, '%s contains %r' % (os.path.relpath(path, ROOT), word))


if __name__ == '__main__':
    unittest.main()
