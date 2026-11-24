"""Runs the JavaScript model tests (tests/model.test.cjs) as part of the Python suite."""

import subprocess
import unittest

from helpers import NODE, ROOT


@unittest.skipUnless(NODE, "Node.js is not installed")
class JavaScriptModelTests(unittest.TestCase):
    def test_node_test_suite_passes(self):
        proc = subprocess.run([NODE, "--test", "tests/model.test.cjs"], cwd=ROOT,
                              capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout[-3000:] + proc.stderr[-2000:])
        self.assertIn("# fail 0", proc.stdout)


if __name__ == "__main__":
    unittest.main()
