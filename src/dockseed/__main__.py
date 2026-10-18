"""Allow running dockseed via `python -m dockseed`."""

import sys

from dockseed.cli import main

if __name__ == "__main__":
    sys.exit(main())
