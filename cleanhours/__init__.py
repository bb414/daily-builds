"""Clean hours: carbon-aware scheduling of AI compute jobs on an invented grid.

The model is a port of the browser app's MODEL block (app/index.html); both give
identical numbers. See README.md for how to use the command-line tool.
"""

from .model import DEFAULT_CONFIG, DEFAULT_JOBS, POLICIES, PRESETS, run, simulate_grid  # noqa: F401

__all__ = ["DEFAULT_CONFIG", "DEFAULT_JOBS", "POLICIES", "PRESETS", "run", "simulate_grid"]
