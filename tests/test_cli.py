import json
from helpers import init_repo, git

import subprocess
from pathlib import Path

from forkroom.cli import build_tui_parser, main, resolve_tui_roots


FIXED_TIME = "2026-06-15T10:00:00+08:00"


def test_cli_init_initializes_experiment(tmp_path: Path, capsys) -> None:
    root = init_repo(tmp_path)

    exit_code = main(
        [
            "init",
            "--root",
            str(root),
            "--id",
            "cli-exp",
            "--title",
            "CLI experiment",
            "--summary",
            "Initialize through the packaged CLI.",
            "--created-at",
            FIXED_TIME,
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["branch"] == "agents/cli-exp"
    assert payload["paths"]["worktree"] == str(root / ".agents" / "exps" / "cli-exp" / "worktree")
    assert (root / ".agents" / "exps" / "cli-exp" / "manifest.json").is_file()


def test_cli_record_session_updates_manifest(tmp_path: Path, capsys) -> None:
    root = tmp_path / "repo"
    manifest_path = root / ".agents" / "exps" / "cli-exp" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(json.dumps({"id": "cli-exp", "updated_at": "old"}), encoding="utf-8")

    exit_code = main(
        [
            "record-session",
            "--root",
            str(root),
            "--exp",
            "cli-exp",
            "--thread-id",
            "thread-1",
            "--title",
            "CLI session",
            "--created-at",
            FIXED_TIME,
            "--updated-at",
            FIXED_TIME,
        ]
    )

    assert exit_code == 0
    assert "recorded session thread-1" in capsys.readouterr().out
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["sessions"][0]["id"] == "thread-1"
    assert manifest["sessions"][0]["title"] == "CLI session"


def test_cli_install_dispatches_to_installer(monkeypatch) -> None:
    calls = []

    def fake_main(argv, prog):
        calls.append((argv, prog))
        return 0

    monkeypatch.setattr("forkroom.cli.installer.main", fake_main)

    exit_code = main(["install", "--root", "/tmp/project"])

    assert exit_code == 0
    assert calls == [(["--root", "/tmp/project"], "forkroom install")]


def test_tui_parser_defaults_to_current_root() -> None:
    args = build_tui_parser().parse_args([])

    assert args.root is None
    assert resolve_tui_roots(args.root) == [Path(".").resolve()]


def test_tui_parser_accepts_repeated_roots_and_dedupes(tmp_path: Path) -> None:
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()

    args = build_tui_parser().parse_args(["--root", str(one), "--root", str(two), "--root", str(one)])

    assert resolve_tui_roots(args.root) == [one.resolve(), two.resolve()]
