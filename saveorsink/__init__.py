"""Save or sink: stress-test automatic saving rules against a student's year of money in and out.

The browser app (app/index.html) is the interactive version. This package runs
the same engine from the command line, over many more simulated years, and
writes reports and files for other tools.
"""

from .model import PRESETS, RULES, default_settings, generate_year, simulate, stress_test, validate_settings

__all__ = ["PRESETS", "RULES", "default_settings", "generate_year", "simulate", "stress_test", "validate_settings"]
