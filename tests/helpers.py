"""Shared helpers for the Python tests."""

import json
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


def node_bridge(command, payload=None):
    """Run the browser app's model in Node.js and return its JSON output."""
    proc = subprocess.run(
        [NODE, BRIDGE, command],
        input=json.dumps(payload) if payload is not None else "",
        capture_output=True, text=True, check=True, timeout=120,
    )
    return json.loads(proc.stdout)


def other(answer):
    return "genuine" if answer == "scam" else "scam"


def fill(session, pick):
    """Fill every trial using pick(trial, stage) -> (answer, confidence)."""
    for t in session["trials"]:
        a, c = pick(t, "initial")
        t["initial"] = {"answer": a, "confidence": c}
        if t["phase"] == "with":
            a, c = pick(t, "final")
            t["final"] = {"answer": a, "confidence": c}
    return session
