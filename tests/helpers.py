"""Shared helpers for the Python tests: paths, sample files, the JavaScript bridge and a readable diff."""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
COMPANION = os.path.join(ROOT, 'companion')
BRIDGE = os.path.join(ROOT, 'tests', 'js_bridge.js')
NODE = shutil.which('node')

if COMPANION not in sys.path:
    sys.path.insert(0, COMPANION)

import examseason as es  # noqa: E402  (needs the path above)
from examseason import model as m  # noqa: E402

FROM = m.day_from_ymd(2026, 11, 30)
TODAY = m.day_from_ymd(2026, 12, 10)


def sample_text(name):
    """A sample file's text, exactly as the browser would read it."""
    with open(os.path.join(DATA, name), encoding='utf-8', newline='') as fh:
        return fh.read()


def load(name, today=TODAY):
    return m.read_project(sample_text(name), today)['project']


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


def py_project_job(job):
    """The Python side of the bridge's project job (see tests/js_bridge.js)."""
    r = m.read_project(job['project'], job['today'])
    p = r['project']
    plan = m.build_plan(p)
    for t in job.get('ticks', []):
        m.tick(p, plan, t[0], t[1], t[2] if len(t) > 2 else True)
    for rt in job.get('rates', []):
        m.rate(p, plan, rt[0], rt[1], rt[2])
    if job.get('replan'):
        m.replan(p, plan, job['replan']['day'], job['replan'].get('min', 0))
        plan = m.build_plan(p)
    for o in job.get('overrides', []):
        m.set_override(p, o['day'], o['minutes'], o['label'])
    if job.get('overrides'):
        plan = m.build_plan(p)
    st = m.status(p, plan, job['today'])
    return plain({
        'messages': r['messages'], 'plan': {k: plan[k] for k in ['from', 'fromMin', 'last', 'notes', 'sessions', 'days', 'exams', 'topics']},
        'status': st, 'summary': m.summary(p, plan, st), 'csv': m.sessions_csv(p, plan), 'statusCsv': m.status_csv(st),
        'ics': m.sessions_ics(p, plan, name=p['name']),
        'icsToday': m.sessions_ics(p, plan, from_day=job['today'], to_day=job['today'], exams=False, skip_done=True),
        'dayText': m.day_text(p, plan, job['today']), 'projectFile': m.project_file(p), 'availabilityCsv': m.availability_csv(p),
        'topics': m.topic_status(p, plan, job['today']), 'markdown': m.checklist_markdown(p, plan),
        'markdownWeek': m.checklist_markdown(p, plan, job['today'], job['today'] + 6),
        'icsAlarm': m.sessions_ics(p, plan, from_day=job['today'], to_day=job['today'] + 2, alarm=10),
        'checks': m.check_inputs(p, plan, job['today']), 'adherence': m.adherence(p, plan, job['today']),
    })
