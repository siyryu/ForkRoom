#!/usr/bin/env python3
"""Compatibility wrapper for the packaged ForkRoom experiment initializer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from forkroom.init_experiment import *  # noqa: F401,F403
from forkroom.init_experiment import main


if __name__ == "__main__":
    raise SystemExit(main())
