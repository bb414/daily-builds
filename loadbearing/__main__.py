"""Lets `python -m loadbearing COMMAND` run the command line."""
import os
import sys

from .cli import main

if __name__ == '__main__':  # worker processes that re-import this module must not rerun the command
    try:
        code = main()
    except BrokenPipeError:
        # The reader stopped early (for example `| head`): drop the rest of the output quietly.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 1
    sys.exit(code)
