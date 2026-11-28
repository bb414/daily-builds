"""Shared helpers for the tests: paths, sample files, the JavaScript bridge, the Python side of a job and a readable diff."""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
COMPANION = os.path.join(ROOT, 'companion')
BRIDGE = os.path.join(ROOT, 'tests', 'js_bridge.js')
SAMPLES = ['challenge-equities.csv', 'futures-messy.csv', 'dealing-account.csv']
NODE = shutil.which('node')

if COMPANION not in sys.path:
    sys.path.insert(0, COMPANION)

import roundtrips as rt  # noqa: E402  (needs the path above)


def sample_text(name):
    """A sample file's text, exactly as the browser would read it."""
    with open(os.path.join(DATA, name), encoding='utf-8', newline='') as fh:
        return fh.read()


def sample_files(names=SAMPLES):
    return [{'name': n, 'text': sample_text(n)} for n in names]


def sample_case(**extra):
    """The sample journal with the three sample exports, as a bridge case."""
    case = {'project': sample_text('sample-journal.json'), 'files': sample_files()}
    case.update(extra)
    return case


def run_bridge(job):
    """Run the browser model on a job and return its answers."""
    proc = subprocess.run([NODE, BRIDGE], input=json.dumps(job), capture_output=True, encoding='utf-8')
    if proc.returncode != 0:
        raise AssertionError('The JavaScript bridge failed:\n' + proc.stderr)
    return json.loads(proc.stdout)


def run_case(job):
    """The Python side of one bridge case."""
    state = rt.read_project(job['project'])['state'] if job.get('project') else rt.empty_state()
    for k, v in (job.get('settings') or {}).items():
        state['settings'][k] = v
    if job.get('carry'):
        state['carry'] = job['carry']
    imp = rt.import_files(state, job.get('files') or [])
    state = imp['state']
    for e in job.get('edits') or []:
        state['journal'] = rt.set_journal(state['journal'], e['id'], e['fields'])
    result = rt.analyse(state)
    start = rt.start_balance(result, result['accounts'])
    out = {'reports': imp['reports'], 'result': {k: v for k, v in result.items() if k != 'settings'}, 'stats': {}, 'breakdowns': {}, 'reviews': []}
    out['stats']['all'] = rt.stats(result['closed'], start)
    for a in result['accounts']:
        out['stats'][a] = rt.stats(rt.filter_trades(result['closed'], a), rt.start_balance(result, [a]))
    for key, _ in rt.BREAKDOWNS:
        out['breakdowns'][key] = rt.breakdown(result['closed'], key)
    out['weekly'] = rt.weekly(result['closed'])
    out['histogram'] = rt.r_histogram(result['closed'])
    for a in [''] + result['accounts']:
        for w in result['weeks']:
            rv = rt.week_review(result, w, a)
            out['reviews'].append({'week': w, 'account': a, 'review': rv, 'text': rt.review_text(rv, result)})
    out['tradesCsv'] = rt.trades_csv(result)
    out['breachesCsv'] = rt.breaches_csv(result)
    out['fillsCsv'] = rt.fills_csv(result)
    out['projectFile'] = rt.project_file(state, job.get('saved') or '2026-11-28')
    return out


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
    if a != b or isinstance(a, bool) != isinstance(b, bool) or (a is None) != (b is None):
        return '%s: Python %r, JavaScript %r' % (where, a, b)
    return None
