"""``python -m quiet_cartel <command>``: see :mod:`quiet_cartel.cli`."""

import sys

from .cli import main

if __name__ == '__main__':
    sys.exit(main())
