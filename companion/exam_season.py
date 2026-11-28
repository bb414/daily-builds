"""Exam season companion: run "python companion/exam_season.py --help"."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from examseason.cli import main  # noqa: E402

if __name__ == '__main__':
    sys.exit(main())
