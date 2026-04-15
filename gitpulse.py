"""gitpulse top-level entrypoint.

All logic lives in the `core` package; this module is deliberately
thin so it can be invoked as `python gitpulse.py ...` for source
runs, and so the pip-installed `gitpulse` console script can reach
the same code path via `core.cli.main_entry`.
"""

import sys

from core.cli import run


def main() -> None:
    sys.exit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
