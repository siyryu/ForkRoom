import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import init_experiment, install as installer, record_session, runs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forkroom",
        description="Read-only TUI and experiment workflow CLI for worktree-backed coding experiments.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.add_parser("tui", help="open the read-only experiment dashboard")
    subparsers.add_parser("init", help="initialize a worktree-backed experiment")
    subparsers.add_parser("install", help="install ForkRoom CLI and skills into a project")
    subparsers.add_parser("record-session", help="record a Codex session on an experiment")
    subparsers.add_parser("run", help="create or update a tracked long-running task")
    return parser


def build_tui_parser(prog: str = "forkroom") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Read-only TUI for worktree-backed coding experiments.",
    )
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help="Repository root to inspect. May be provided multiple times. Defaults to the current directory.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> Optional[int]:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if raw_args and raw_args[0] in {"-h", "--help"}:
        build_parser().parse_args(raw_args)
        return 0
    if raw_args and raw_args[0] == "init":
        return init_experiment.main(raw_args[1:], prog="forkroom init")
    if raw_args and raw_args[0] == "install":
        return installer.main(raw_args[1:], prog="forkroom install")
    if raw_args and raw_args[0] == "record-session":
        return record_session.main(raw_args[1:], prog="forkroom record-session")
    if raw_args and raw_args[0] == "run":
        return runs.main(raw_args[1:], prog="forkroom run")
    if raw_args and raw_args[0] == "tui":
        return run_tui(raw_args[1:], prog="forkroom tui")
    return run_tui(raw_args, prog="forkroom")


def run_tui(argv: Sequence[str], prog: str) -> None:
    from .app import ForkRoomApp

    args = build_tui_parser(prog=prog).parse_args(argv)
    app = ForkRoomApp(roots=resolve_tui_roots(args.root))
    app.run()
    return None


def resolve_tui_roots(raw_roots: Optional[Sequence[str]]) -> Sequence[Path]:
    roots = raw_roots or ["."]
    resolved_roots = []
    seen = set()
    for root in roots:
        resolved = Path(root).expanduser().resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        resolved_roots.append(resolved)
    return resolved_roots
