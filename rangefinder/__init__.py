"""Range finder: size a market or a business case in honest ranges.

The browser app (app/index.html) is the interactive version. This package
runs the same models from the command line, writes reports and sample files,
and adds checks that are too heavy for a browser tab.
"""

from .model import TEMPLATES, analyse, format_value, simulate, validate_model

__all__ = ["TEMPLATES", "analyse", "format_value", "simulate", "validate_model"]
