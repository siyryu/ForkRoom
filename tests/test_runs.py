import json
from pathlib import Path

import pytest

from helpers import git, init_repo
from forkroom.cli import main as cli_main
from forkroom.runs import parse_eta
from forkroom.scanner import scan_repositories


FIXED_TIME = "2026-06-15T10:00:00+08:00"
ETA_ONE = "2026-06-15T11:00:00+08:00"
ETA_TWO = "2026-06-15T12:00:00+08:00"


def test_cli_run_lifecycle_writes_events_and_updates_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = init_repo(tmp_path)
    write_experiment(root, "alpha")

    exit_code = cli_main(
        [
            "run",
            "start",
            "--root",
            str(root),
            "--exp",
            "alpha",
            "--id",
            "train-model",
            "--title",
            "Train model",
            "--session-id",
            "session-1",
            "--eta",
            ETA_ONE,
            "--completed",
            "10",
            "--total",
            "100",
            "--message",
            "Starting",
            "--created-at",
            FIXED_TIME,
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    run_path = root / ".agents" / "exps" / "alpha" / "runs" / "train-model.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["status"] == "running"
    assert run["session_id"] == "session-1"
    assert run["completed"] == 10
    assert run["total"] == 100
    assert run["events"][0]["type"] == "start"

    exit_code = cli_main(
        [
            "run",
            "update",
            "--root",
            str(root),
            "--exp",
            "alpha",
            "--id",
            "train-model",
            "--status",
            "waiting",
            "--eta",
            ETA_TWO,
            "--completed",
            "40",
            "--message",
            "Waiting for quota",
            "--updated-at",
            ETA_ONE,
        ]
    )

    assert exit_code == 0
    run = json.loads(run_path.read_text(encoding="utf-8"))
    assert run["status"] == "waiting"
    assert run["completed"] == 40
    assert run["total"] == 100
    assert run["message"] == "Waiting for quota"
    assert len(run["events"]) == 2

    exit_code = cli_main(
        [
            "run",
            "succeed",
            "--root",
            str(root),
            "--exp",
            "alpha",
            "--id",
            "train-model",
            "--message",
            "Done",
            "--updated-at",
            ETA_TWO,
        ]
    )

    assert exit_code == 0
    run = json.loads(run_path.read_text(encoding="utf-8"))
    manifest = json.loads((root / ".agents" / "exps" / "alpha" / "manifest.json").read_text(encoding="utf-8"))
    assert run["status"] == "succeeded"
    assert run["completed"] == 100
    assert run["total"] == 100
    assert run["ended_at"].startswith("2026-06-15T")
    assert run["events"][-1]["status"] == "succeeded"
    assert manifest["updated_at"].startswith("2026-06-15T")


def test_session_can_only_have_one_active_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = init_repo(tmp_path)
    write_experiment(root, "alpha")
    write_experiment(root, "beta")

    assert start_run(root, "alpha", "first", "session-1") == 0
    capsys.readouterr()
    exit_code = start_run(root, "beta", "second", "session-1")
    output = capsys.readouterr().out
    assert exit_code == 1
    assert json.loads(output)["error"]["code"] == "active_session_run_exists"

    assert cli_main(
        [
            "run",
            "fail",
            "--root",
            str(root),
            "--exp",
            "alpha",
            "--id",
            "first",
            "--message",
            "Stopped",
            "--updated-at",
            ETA_TWO,
        ]
    ) == 0
    assert start_run(root, "beta", "after-finish", "session-1") == 0


def test_terminal_run_rejects_later_updates(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = init_repo(tmp_path)
    write_experiment(root, "alpha")

    assert start_run(root, "alpha", "one-shot", "session-1") == 0
    assert cli_main(
        [
            "run",
            "cancel",
            "--root",
            str(root),
            "--exp",
            "alpha",
            "--id",
            "one-shot",
            "--updated-at",
            ETA_ONE,
        ]
    ) == 0
    capsys.readouterr()

    exit_code = cli_main(
        [
            "run",
            "update",
            "--root",
            str(root),
            "--exp",
            "alpha",
            "--id",
            "one-shot",
            "--eta",
            ETA_TWO,
        ]
    )

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "terminal_run"


def test_parse_eta_supports_relative_duration() -> None:
    assert parse_eta("2h", now_text_datetime()).startswith("2026-06-15T12:00:00")


def test_scanner_loads_runs_and_warns_for_template_violations(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    write_experiment(root, "alpha")
    write_experiment(root, "beta")
    write_run(
        root,
        "alpha",
        "manual-one",
        {
            "id": "manual-one",
            "title": "Manual one",
            "session_id": "shared-session",
            "status": "running",
            "completed": 50,
            "total": 100,
            "estimated_end_at": ETA_TWO,
            "updated_at": ETA_ONE,
            "events": [
                {
                    "type": "start",
                    "status": "running",
                    "completed": 10,
                    "total": 100,
                    "estimated_end_at": ETA_ONE,
                    "updated_at": FIXED_TIME,
                }
            ],
        },
    )
    write_run(
        root,
        "beta",
        "manual-two",
        {
            "id": "manual-two",
            "title": "Manual two",
            "session_id": "shared-session",
            "status": "waiting",
            "completed": 20,
            "total": 100,
            "updated_at": ETA_ONE,
            "events": [
                {"type": "start", "status": "running", "estimated_end_at": ETA_ONE, "updated_at": FIXED_TIME},
                {"type": "bad", "status": "succeeded", "updated_at": ETA_ONE},
                {"type": "bad", "status": "running", "estimated_end_at": ETA_TWO, "updated_at": ETA_TWO},
            ],
        },
    )

    snapshot = scan_repositories([root])

    experiments = {experiment.id: experiment for experiment in snapshot.experiments}
    assert experiments["alpha"].runs[0].id == "manual-one"
    alpha_warnings = "\n".join(experiments["alpha"].warnings)
    beta_warnings = "\n".join(experiments["beta"].warnings)
    assert "multiple active runs" in alpha_warnings
    assert "non-terminal status requires estimated_end_at" in beta_warnings
    assert "occurs after terminal status" in beta_warnings


def start_run(root: Path, exp_id: str, run_id: str, session_id: str) -> int:
    return cli_main(
        [
            "run",
            "start",
            "--root",
            str(root),
            "--exp",
            exp_id,
            "--id",
            run_id,
            "--title",
            run_id,
            "--session-id",
            session_id,
            "--eta",
            ETA_ONE,
            "--completed",
            "0",
            "--total",
            "1",
            "--created-at",
            FIXED_TIME,
        ]
    )


def write_experiment(root: Path, exp_id: str) -> None:
    git(root, "branch", "agents/{0}".format(exp_id), "HEAD")
    exp_path = root / ".agents" / "exps" / exp_id
    (exp_path / "worktree").mkdir(parents=True)
    (exp_path / "outputs").mkdir()
    (exp_path / "logs").mkdir()
    (exp_path / "manifest.json").write_text(
        json.dumps(
            {
                "id": exp_id,
                "title": exp_id.title(),
                "branch": "agents/{0}".format(exp_id),
                "updated_at": FIXED_TIME,
            }
        ),
        encoding="utf-8",
    )


def write_run(root: Path, exp_id: str, run_id: str, payload: dict) -> None:
    path = root / ".agents" / "exps" / exp_id / "runs"
    path.mkdir(parents=True, exist_ok=True)
    (path / "{0}.json".format(run_id)).write_text(json.dumps(payload), encoding="utf-8")


def now_text_datetime():
    from datetime import datetime

    return datetime.fromisoformat(FIXED_TIME)
