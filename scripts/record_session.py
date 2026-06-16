#!/usr/bin/env python3
"""Compatibility wrapper for the packaged Vibe Board session recorder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vibe_board.record_session import *  # noqa: F401,F403
from vibe_board.record_session import main


if __name__ == "__main__":
    raise SystemExit(main())
