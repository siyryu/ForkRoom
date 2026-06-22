#!/usr/bin/env python3
"""Compatibility wrapper for the packaged ForkRoom session recorder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forkroom.record_session import *  # noqa: F401,F403
from forkroom.record_session import main


if __name__ == "__main__":
    raise SystemExit(main())
