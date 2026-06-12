import argparse
from pathlib import Path
from typing import Optional, Sequence

from .app import VibeBoardApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibe-board",
        description="Read-only TUI for worktree-backed coding experiments.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to inspect. Defaults to the current directory.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    app = VibeBoardApp(root=Path(args.root).expanduser().resolve())
    app.run()
