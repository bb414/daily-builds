"""Shared helpers for the Python tests."""

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app" / "index.html"
NODE = shutil.which("node")


def run_js(jobs):
    """Run jobs through the app's own model in Node.js and return the parsed results."""
    out = subprocess.run([NODE, str(ROOT / "tests" / "run_model.js")], input=json.dumps(jobs),
                         capture_output=True, text=True, check=True, timeout=600)
    return json.loads(out.stdout)


def first_difference(a, b, path="$"):
    """Exact deep comparison (floats must match bit for bit). Returns a description or None."""
    if isinstance(a, bool) or isinstance(b, bool):
        return None if a is b or a == b and type(a) is type(b) else "%s: %r != %r" % (path, a, b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return None if float(a) == float(b) else "%s: %r != %r" % (path, a, b)
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b):
            return "%s: keys differ %s" % (path, sorted(set(a) ^ set(b)))
        for k in a:
            d = first_difference(a[k], b[k], path + "." + k)
            if d:
                return d
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return "%s: lengths %d != %d" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, "%s[%d]" % (path, i))
            if d:
                return d
        return None
    return None if a == b else "%s: %r != %r" % (path, a, b)
