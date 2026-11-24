"""Shared helpers for the Python tests."""

import json
import math
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

NODE = shutil.which("node")
BRIDGE = os.path.join(ROOT, "tests", "load_model.cjs")
APP = os.path.join(ROOT, "app", "index.html")


def node_bridge(command, payload):
    """Run the browser app's own model in Node.js and return its JSON output."""
    proc = subprocess.run([NODE, BRIDGE, command], input=json.dumps(payload),
                          capture_output=True, text=True, check=True, timeout=300)
    return json.loads(proc.stdout)


def assert_same(test, a, b, path="value"):
    """Deep comparison that allows only floating-point noise."""
    if isinstance(a, dict) and isinstance(b, dict):
        test.assertEqual(sorted(a), sorted(b), "keys differ at %s" % path)
        for k in a:
            assert_same(test, a[k], b[k], path + "." + k)
    elif isinstance(a, list) and isinstance(b, list):
        test.assertEqual(len(a), len(b), "lengths differ at %s" % path)
        for i, (x, y) in enumerate(zip(a, b)):
            assert_same(test, x, y, "%s[%d]" % (path, i))
    elif a is None or b is None or isinstance(a, (str, bool)) or isinstance(b, (str, bool)):
        test.assertEqual(a, b, "values differ at %s" % path)
    else:
        test.assertTrue(a == b or math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12), "%s: %r != %r" % (path, a, b))
