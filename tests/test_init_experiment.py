from __future__ import annotations
from helpers import init_repo, git


import json
import os
import subprocess
from pathlib import Path

import pytest

from forkroom.init_experiment import InitExperimentError, init_experiment, main, branch_exists


FIXED_TIME = "2026-06-15T10:00:00+08:00"


def test_cli_initializes_experiment_and_records_session(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = init_repo(
        tmp_path,
        files={"local-config.txt": "local config\n"},
        map_config={
            "version": 1,
            "links": [
                {
                    "source": "local-config.txt",
                    "target": ".local/local-config.txt",
                    "required": True,
                    "description": "Local config",
                }
            ],
        },
    )

    exit_code = main(
        [
            "--root",
            str(root),
            "--id",
            "alpha-exp",
            "--title",
            "Alpha experiment",
            "--summary",
            "Prepare an isolated experiment.",
            "--session-title",
            "Alpha startup",
            "--thread-id",
            "thread-1",
            "--status",
            "running",
            "--created-at",
            FIXED_TIME,
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["branch"] == "forkroom/alpha-exp"
    assert payload["session"] == {"recorded": True, "thread_id": "thread-1"}
    assert [step["name"] for step in payload["steps"]][-1] == "final-validation"

    exp_path = root / ".forkroom" / "exps" / "alpha-exp"
    worktree_path = exp_path / "worktree"
    manifest = json.loads((exp_path / "manifest.json").read_text(encoding="utf-8"))

    assert payload["status"] == "running"
    assert manifest["status"] == "running"
    assert manifest["created_at"] == FIXED_TIME
    assert manifest["updated_at"] == FIXED_TIME
    assert manifest["sessions"][0]["id"] == "thread-1"
    assert manifest["sessions"][0]["title"] == "Alpha startup"
    assert not (exp_path / "plan.md").exists()
    assert (exp_path / "outputs").is_dir()
    assert (exp_path / "logs").is_dir()
    assert worktree_path.is_dir()

    link_path = worktree_path / ".local" / "local-config.txt"
    assert link_path.is_symlink()
    assert os.readlink(link_path) == str((root / "local-config.txt").resolve())
    assert branch_exists(root, "forkroom/alpha-exp")
    assert str(worktree_path) in git(root, "worktree", "list", "--porcelain").stdout


def test_optional_mapping_source_missing_is_reported_without_failing(tmp_path: Path) -> None:
    root = init_repo(
        tmp_path,
        map_config={
            "version": 1,
            "links": [
                {
                    "source": ".env.local",
                    "target": ".env.local",
                    "required": False,
                    "description": "Optional local environment",
                }
            ],
        },
    )

    payload = init_experiment(
        root=root,
        exp_id="optional-map",
        title="Optional map",
        summary="Exercise optional worktree-map sources.",
        created_at=FIXED_TIME,
    )

    assert payload["ok"] is True
    assert payload["status"] == "running"
    assert payload["worktree_map"]["links"][0]["status"] == "skipped"
    assert payload["warnings"] == [
        {
            "code": "optional_source_missing",
            "source": ".env.local",
            "target": ".env.local",
        }
    ]
    assert not os.path.lexists(str(root / ".forkroom" / "exps" / "optional-map" / "worktree" / ".env.local"))


def test_rejects_existing_branch_conflict_before_creating_directories(tmp_path: Path) -> None:
    root = init_repo(tmp_path)
    git(root, "branch", "forkroom/conflict-exp", "HEAD")

    with pytest.raises(InitExperimentError) as raised:
        init_experiment(
            root=root,
            exp_id="conflict-exp",
            title="Conflict",
            summary="Reject an existing branch.",
            created_at=FIXED_TIME,
        )

    assert raised.value.code == "branch_exists"
    assert raised.value.step == "branch"
    assert not (root / ".forkroom" / "exps" / "conflict-exp").exists()


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"exp_id": "Bad_Id", "status": "draft"}, "invalid_id"),
        ({"exp_id": "bad-status", "status": "paused"}, "invalid_status"),
    ],
)
def test_rejects_validation_errors(tmp_path: Path, kwargs: dict, code: str) -> None:
    root = init_repo(tmp_path)

    with pytest.raises(InitExperimentError) as raised:
        init_experiment(
            root=root,
            title="Validation",
            summary="Reject invalid input.",
            created_at=FIXED_TIME,
            **kwargs,
        )

    assert raised.value.code == code
    assert raised.value.step == "validation"


def test_rejects_required_mapping_source_missing(tmp_path: Path) -> None:
    root = init_repo(
        tmp_path,
        map_config={
            "version": 1,
            "links": [
                {
                    "source": "missing.local",
                    "target": "missing.local",
                    "required": True,
                    "description": "Required local prerequisite",
                }
            ],
        },
    )

    with pytest.raises(InitExperimentError) as raised:
        init_experiment(
            root=root,
            exp_id="missing-required-map",
            title="Missing required map",
            summary="Reject missing required local prerequisites.",
            created_at=FIXED_TIME,
        )

    assert raised.value.code == "required_source_missing"
    assert raised.value.step == "worktree-map"
    assert not branch_exists(root, "forkroom/missing-required-map")
