"""Runs the JavaScript tests (tests/app_model.test.js) so one command covers everything."""

import shutil
import subprocess
import unittest
from pathlib import Path

NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is not installed")
class JavaScriptTests(unittest.TestCase):
    def test_node_test_suite_passes(self):
        result = subprocess.run([NODE, "--test", str(Path(__file__).with_name("app_model.test.js"))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("# fail 0", result.stdout)


if __name__ == "__main__":
    unittest.main()
