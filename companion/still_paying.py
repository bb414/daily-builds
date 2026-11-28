"""Still paying? companion, the command line entry point.

    python companion/still_paying.py scan data/
    python companion/still_paying.py monthly exports/ --history reviews/
    python companion/still_paying.py budget data/ --months 6
    python companion/still_paying.py template --out template.csv

Run with --help for every option.
"""

import sys

from stillpaying.cli import main

if __name__ == '__main__':
    sys.exit(main())
