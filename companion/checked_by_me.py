"""Checked by me, the companion: run `python companion/checked_by_me.py --help`."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from checkedbyme.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
