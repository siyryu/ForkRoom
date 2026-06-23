import argparse
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence


DEFAULT_SOURCE = "git+https://github.com/siyryu/forkroom.git"


Runner = Callable[..., subprocess.CompletedProcess]

LEGACY_FORKROOM_SKILL_ENTRIES = (
    "forkroom-init.md",
    "forkroom-record.md",
    "forkroom-run.md",
    "forkroom-merge.md",
    "forkroom-run",
)


class InstallError(Exception):
    """Raised when ForkRoom cannot be installed into a project."""


@dataclass(frozen=True)
class InstallResult:
    root: Path
    skills_dir: Path
    installed_entries: Sequence[str]
    tool_installed: bool


def main(argv: Optional[Sequence[str]] = None, prog: Optional[str] = None) -> int:
    parser = build_parser(prog=prog or "forkroom install")
    args = parser.parse_args(list(argv or []))

    try:
        result = install_forkroom(
            root=Path(args.root),
            source=args.source,
            link_skills=args.link_skills,
            install_tool=not args.no_tool_install,
        )
    except InstallError as exc:
        print("install: {0}".format(exc), file=sys.stderr)
        return 1

    if result.tool_installed:
        print("CLI installed/updated.")
    else:
        print("CLI install skipped.")
    print("Skills installed to {0}.".format(result.skills_dir))
    print("Next: run `forkroom` from {0}.".format(result.root))
    return 0


def build_parser(prog: str = "forkroom install") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Install ForkRoom CLI and skills into a project.",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Project root where .codex/skills should be installed. Defaults to the current directory.",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_SOURCE,
        help="ForkRoom package source. Defaults to the public GitHub repository.",
    )
    parser.add_argument(
        "--link-skills",
        action="store_true",
        help="Symlink skills from --source instead of copying them.",
    )
    parser.add_argument(
        "--no-tool-install",
        action="store_true",
        help="Skip installing/updating the global forkroom CLI with uv.",
    )
    return parser


def install_forkroom(
    *,
    root: Path,
    source: str,
    link_skills: bool,
    install_tool: bool,
    runner: Runner = subprocess.run,
) -> InstallResult:
    resolved_root = root.expanduser().resolve(strict=False)
    if not resolved_root.exists():
        raise InstallError("project root does not exist: {0}".format(resolved_root))
    if not resolved_root.is_dir():
        raise InstallError("project root is not a directory: {0}".format(resolved_root))

    if install_tool:
        install_cli_tool(source, runner=runner)

    skills_dir = resolved_root / ".codex" / "skills"
    with resolve_skills_source(source, runner=runner) as source_skills:
        installed_entries = install_skills(source_skills, skills_dir, link_skills=link_skills)

    return InstallResult(
        root=resolved_root,
        skills_dir=skills_dir,
        installed_entries=installed_entries,
        tool_installed=install_tool,
    )


def install_cli_tool(source: str, *, runner: Runner = subprocess.run) -> None:
    run_checked(["uv", "tool", "install", "--force", source], runner=runner)


@contextmanager
def resolve_skills_source(source: str, *, runner: Runner = subprocess.run) -> Iterator[Path]:
    local_source = local_source_path(source)
    if local_source is not None:
        yield skills_dir_from_source(local_source)
        return

    clone_url, ref = git_clone_spec(source)
    with tempfile.TemporaryDirectory(prefix="forkroom-install-") as tmp_dir:
        checkout = Path(tmp_dir) / "forkroom"
        clone_command = ["git", "clone", "--filter=blob:none", "--sparse"]
        if ref:
            clone_command.extend(["--branch", ref])
        clone_command.extend(["--depth", "1", clone_url, str(checkout)])
        run_checked(clone_command, runner=runner)
        run_checked(["git", "-C", str(checkout), "sparse-checkout", "set", "skills"], runner=runner)
        yield skills_dir_from_source(checkout)


def local_source_path(source: str) -> Optional[Path]:
    path = Path(source).expanduser()
    if path.exists():
        return path.resolve()
    return None


def skills_dir_from_source(source: Path) -> Path:
    skills_dir = source / "skills"
    if not skills_dir.is_dir():
        raise InstallError("source does not contain a skills directory: {0}".format(source))
    return skills_dir


def git_clone_spec(source: str) -> tuple[str, Optional[str]]:
    clone_spec = source[4:] if source.startswith("git+") else source
    clone_spec = clone_spec.split("#", 1)[0]
    if ".git@" in clone_spec:
        clone_url, ref = clone_spec.rsplit(".git@", 1)
        return clone_url + ".git", ref
    return clone_spec, None


def install_skills(source_skills: Path, target_skills: Path, *, link_skills: bool) -> Sequence[str]:
    target_skills.mkdir(parents=True, exist_ok=True)
    installed = []

    for legacy_entry in LEGACY_FORKROOM_SKILL_ENTRIES:
        target_entry = target_skills / legacy_entry
        if target_entry.is_symlink() or target_entry.exists():
            remove_existing(target_entry)

    for source_entry in sorted(source_skills.iterdir(), key=lambda path: path.name):
        if source_entry.name.startswith("."):
            continue
        target_entry = target_skills / source_entry.name
        remove_existing(target_entry)
        if link_skills:
            target_entry.symlink_to(source_entry.resolve(), target_is_directory=source_entry.is_dir())
        elif source_entry.is_dir():
            shutil.copytree(source_entry, target_entry, symlinks=True)
        else:
            shutil.copy2(source_entry, target_entry)
        installed.append(source_entry.name)

    return installed


def remove_existing(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def run_checked(command: Sequence[str], *, runner: Runner = subprocess.run) -> None:
    try:
        runner(list(command), check=True)
    except FileNotFoundError as exc:
        raise InstallError("{0} is required but was not found".format(command[0])) from exc
    except subprocess.CalledProcessError as exc:
        raise InstallError("command failed: {0}".format(" ".join(command))) from exc
