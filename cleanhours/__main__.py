import os
import sys

from .cli import main

try:
    sys.exit(main())
except BrokenPipeError:
    # The output was cut short by a pipe (for example `| head`): stop quietly.
    os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
    sys.exit(1)
