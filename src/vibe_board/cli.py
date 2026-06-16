import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .app import VibeBoardApp
from . import init_experiment, record_session


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibe-board",
        description="Read-only TUI and experiment workflow CLI for worktree-backed coding experiments.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.add_parser("tui", help="open the read-only experiment dashboard")
    subparsers.add_parser("init", help="initialize a worktree-backed experiment")
    subparsers.add_parser("record-session", help="record a Codex session on an experiment")
    return parser


def build_tui_parser(prog: str = "vibe-board") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Read-only TUI for worktree-backed coding experiments.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Repository root to inspect. Defaults to the current directory.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> Optional[int]:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] in {"-h", "--help"}:
        build_parser().parse_args(raw_args)
        return 0
    if raw_args and raw_args[0] == "init":
        return init_experiment.main(raw_args[1:], prog="vibe-board init")
    if raw_args and raw_args[0] == "record-session":
        return record_session.main(raw_args[1:], prog="vibe-board record-session")
    if raw_args and raw_args[0] == "tui":
        return run_tui(raw_args[1:], prog="vibe-board tui")
    return run_tui(raw_args, prog="vibe-board")


def run_tui(argv: Sequence[str], prog: str) -> None:
    args = build_tui_parser(prog=prog).parse_args(argv)
    app = VibeBoardApp(root=Path(args.root).expanduser().resolve())
    app.run()
    return None
