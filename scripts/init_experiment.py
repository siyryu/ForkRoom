#!/usr/bin/env python3
"""Compatibility wrapper for the packaged Vibe Board experiment initializer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vibe_board.init_experiment import *  # noqa: F401,F403
from vibe_board.init_experiment import main


if __name__ == "__main__":
    raise SystemExit(main())
