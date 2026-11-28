"""Round trips companion: run `python companion/round_trips.py --help` for the commands."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from roundtrips.cli import main  # noqa: E402  (needs the path above)

if __name__ == '__main__':
    sys.exit(main())
