"""Shared helpers for the tests: paths, sample files, the JavaScript bridge and a readable diff."""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
COMPANION = os.path.join(ROOT, 'companion')
BRIDGE = os.path.join(ROOT, 'tests', 'js_bridge.js')
SAMPLES = ['current-account.csv', 'credit-card.csv', 'spending-app.csv', 'messy-export.csv']
NODE = shutil.which('node')

if COMPANION not in sys.path:
    sys.path.insert(0, COMPANION)

import stillpaying as sp  # noqa: E402  (needs the path above)


def sample_text(name):
    """A sample export's text, exactly as the browser would read it."""
    with open(os.path.join(DATA, name), encoding='utf-8', newline='') as fh:
        return fh.read()


def sample_files(names=SAMPLES):
    """Sample exports as the {'name', 'text'} records analyse() takes."""
    return [{'name': n, 'text': sample_text(n)} for n in names]


def truncate(text, last_day):
    """Keep the lines of a simple one-row-per-line export dated on or before a day (header lines are kept)."""
    keep = []
    for line in text.splitlines(keepends=True):
        first = line.split(',')[0].strip().strip('"').lstrip('\ufeff')
        day = sp.parse_date(first, 'DMY')
        if day is None or day <= last_day:
            keep.append(line)
    return ''.join(keep)


def run_bridge(job):
    """Run the browser model on a job and return its answers."""
    proc = subprocess.run([NODE, BRIDGE], input=json.dumps(job), capture_output=True, encoding='utf-8')
    if proc.returncode != 0:
        raise AssertionError('The JavaScript bridge failed:\n' + proc.stderr)
    return json.loads(proc.stdout)


def plain(value):
    """Python data as the JSON it would become, so it compares like for like with the bridge's answers."""
    return json.loads(json.dumps(value))


def first_difference(a, b, where='$'):
    """The path and values of the first place two JSON values differ, or None when they are the same."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if k not in a or k not in b:
                return '%s.%s: only in %s' % (where, k, 'Python' if k in a else 'JavaScript')
            found = first_difference(a[k], b[k], '%s.%s' % (where, k))
            if found:
                return found
        return None
    if isinstance(a, list) and isinstance(b, list):
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, '%s[%d]' % (where, i))
            if found:
                return found
        if len(a) != len(b):
            return '%s: %d items in Python, %d in JavaScript' % (where, len(a), len(b))
        return None
    if a != b or isinstance(a, bool) != isinstance(b, bool):
        return '%s: Python %r, JavaScript %r' % (where, a, b)
    return None
