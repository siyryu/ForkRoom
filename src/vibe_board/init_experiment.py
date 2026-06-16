#!/usr/bin/env python3
"""Initialize a Vibe Board experiment worktree."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .record_session import RecordSessionError, record_session


EXPS_DIR = Path(".agents") / "exps"
MAP_PATH = Path(".vibe-board") / "worktree-map.json"
ALLOWED_STATUSES = {"draft", "running", "ready", "handoff", "merged", "archived"}
EXP_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


class InitExperimentError(Exception):
    """Raised when an experiment cannot be initialized safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        step: str,
        steps: Sequence[Mapping[str, Any]],
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.step = step
        self.steps = [dict(item) for item in steps]
        self.details = dict(details or {})

    def to_payload(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "step": self.step,
                "message": str(self),
                "details": json_safe(self.details),
            },
            "steps": json_safe(self.steps),
        }


@dataclass(frozen=True)
class LinkPlan:
    source: str
    target: str
    required: bool
    description: str
    source_path: Path
    target_path: Path
    source_exists: bool
    should_link: bool


@dataclass(frozen=True)
class MapPlan:
    path: Path
    exists: bool
    root: Path
    worktree_path: Path
    links: List[LinkPlan]


def build_parser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Initialize .agents/exps/<id> with a branch, worktree, manifest, and local symlinks.",
    )
    parser.add_argument("--root", default=".", help="Repository root. Defaults to the current directory.")
    parser.add_argument("--id", default="", help="Lowercase hyphenated experiment id.")
    parser.add_argument("--title", default="", help="Human-readable experiment title.")
    parser.add_argument("--summary", default="", help="One-sentence experiment summary.")
    parser.add_argument("--session-title", default="", help="Title for the recorded Codex session.")
    parser.add_argument("--thread-id", default="", help="Optional Codex thread/session id.")
    parser.add_argument("--status", default="running", help="Experiment status. Defaults to running.")
    parser.add_argument(
        "--plan-content",
        default=None,
        help="Optional plan.md content. plan.md is not written when this is omitted.",
    )
    parser.add_argument(
        "--created-at",
        default="",
        help="Timestamp for manifest and session metadata. Defaults to the current local time.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None, prog: Optional[str] = None) -> int:
    args = build_parser(prog=prog).parse_args(argv)
    try:
        payload = init_experiment(
            root=Path(args.root),
            exp_id=args.id,
            title=args.title,
            summary=args.summary,
            session_title=args.session_title,
            thread_id=args.thread_id,
            status=args.status,
            plan_content=args.plan_content,
            created_at=args.created_at,
        )
    except InitExperimentError as exc:
        print_json(exc.to_payload())
        return 1

    print_json(payload)
    return 0


def init_experiment(
    root: Path,
    exp_id: str,
    title: str,
    summary: str,
    session_title: str = "",
    thread_id: str = "",
    status: str = "running",
    plan_content: Optional[str] = None,
    created_at: str = "",
) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    root = resolve_root(root, steps)
    validate_inputs(exp_id, title, summary, status, steps)
    created_at = created_at.strip() or now_text()

    repo_step(root, steps)
    git_status_step(root, steps, warnings)

    branch = "agents/{0}".format(exp_id)
    exps_path = root / EXPS_DIR
    exp_path = safe_child(exps_path, exp_id, "experiment", "directories", steps)
    outputs_path = exp_path / "outputs"
    logs_path = exp_path / "logs"
    worktree_path = exp_path / "worktree"
    manifest_path = exp_path / "manifest.json"
    plan_path = exp_path / "plan.md"

    if os.path.lexists(str(exp_path)):
        fail(
            steps,
            "directories",
            "experiment_exists",
            "experiment directory already exists",
            {"path": exp_path},
        )
    if branch_exists(root, branch):
        fail(
            steps,
            "branch",
            "branch_exists",
            "branch already exists",
            {"branch": branch},
        )

    map_plan = build_map_plan(root, worktree_path, steps)

    try:
        outputs_path.mkdir(parents=True)
        logs_path.mkdir()
    except OSError as exc:
        fail(steps, "directories", "mkdir_failed", "could not create experiment directories", {"error": str(exc)})
    add_step(steps, "directories", "ok", "created experiment, outputs, and logs directories", {"path": exp_path})

    run_git_checked(root, ["branch", branch, "HEAD"], steps, "branch", "git_branch_failed")
    add_step(steps, "branch", "ok", "created experiment branch", {"branch": branch})

    run_git_checked(root, ["worktree", "add", str(worktree_path), branch], steps, "worktree", "git_worktree_failed")
    add_step(steps, "worktree", "ok", "created experiment worktree", {"path": worktree_path})

    manifest = {
        "id": exp_id,
        "title": title.strip(),
        "status": status.strip(),
        "branch": branch,
        "created_at": created_at,
        "updated_at": created_at,
        "summary": summary.strip(),
        "agent": "codex",
    }
    write_json_file(manifest_path, manifest, steps, "manifest")
    add_step(steps, "manifest", "ok", "wrote manifest.json", {"path": manifest_path})

    plan_written = False
    if plan_content is None:
        add_step(steps, "plan", "skipped", "plan.md not written because no plan content was provided")
    else:
        try:
            plan_path.write_text(text_with_trailing_newline(plan_content), encoding="utf-8")
        except OSError as exc:
            fail(steps, "plan", "plan_write_failed", "could not write plan.md", {"error": str(exc)})
        plan_written = True
        add_step(steps, "plan", "ok", "wrote plan.md", {"path": plan_path})

    thread_id = thread_id.strip()
    if thread_id:
        try:
            record_session(
                root=root,
                exp_id=exp_id,
                thread_id=thread_id,
                title=session_title.strip() or title.strip(),
                status=status.strip(),
                created_at=created_at,
                updated_at=created_at,
            )
        except RecordSessionError as exc:
            fail(steps, "session", "record_session_failed", "could not record session", {"error": str(exc)})
        add_step(steps, "session", "ok", "recorded Codex session", {"thread_id": thread_id})
    else:
        add_step(steps, "session", "skipped", "no thread id provided")

    link_results = apply_worktree_map(map_plan, steps, warnings)
    final_validation(
        root=root,
        exp_id=exp_id,
        branch=branch,
        exp_path=exp_path,
        outputs_path=outputs_path,
        logs_path=logs_path,
        worktree_path=worktree_path,
        manifest_path=manifest_path,
        plan_path=plan_path,
        plan_written=plan_written,
        thread_id=thread_id,
        link_results=link_results,
        steps=steps,
    )

    return {
        "ok": True,
        "id": exp_id,
        "title": title.strip(),
        "status": status.strip(),
        "root": str(root),
        "branch": branch,
        "paths": {
            "experiment": str(exp_path),
            "worktree": str(worktree_path),
            "manifest": str(manifest_path),
            "plan": str(plan_path) if plan_written else None,
        },
        "session": {
            "recorded": bool(thread_id),
            "thread_id": thread_id or None,
        },
        "worktree_map": {
            "path": str(map_plan.path),
            "exists": map_plan.exists,
            "links": link_results,
        },
        "warnings": warnings,
        "steps": steps,
    }


def resolve_root(root: Path, steps: List[Dict[str, Any]]) -> Path:
    requested = root.expanduser().resolve(strict=False)
    if not requested.is_dir():
        fail(steps, "root", "root_missing", "repository root does not exist", {"path": requested})

    code, out, err = run_git(requested, ["rev-parse", "--show-toplevel"])
    if code != 0:
        fail(steps, "root", "not_git_repository", "root is not inside a git repository", {"error": short_error(err)})

    resolved = Path(out.strip()).resolve(strict=False)
    add_step(steps, "root", "ok", "resolved repository root", {"requested": requested, "root": resolved})
    return resolved


def validate_inputs(
    exp_id: str,
    title: str,
    summary: str,
    status: str,
    steps: List[Dict[str, Any]],
) -> None:
    if not exp_id.strip():
        fail(steps, "validation", "missing_id", "experiment id is required")
    if not EXP_ID_RE.match(exp_id.strip()):
        fail(
            steps,
            "validation",
            "invalid_id",
            "experiment id must be lowercase, hyphenated, and alphanumeric at both ends",
            {"id": exp_id},
        )
    if not title.strip():
        fail(steps, "validation", "missing_title", "title is required")
    if not summary.strip():
        fail(steps, "validation", "missing_summary", "summary is required")
    if status.strip() not in ALLOWED_STATUSES:
        fail(
            steps,
            "validation",
            "invalid_status",
            "status is not allowed",
            {"status": status, "allowed": sorted(ALLOWED_STATUSES)},
        )
    add_step(steps, "validation", "ok", "validated CLI inputs")


def repo_step(root: Path, steps: List[Dict[str, Any]]) -> None:
    run_git_checked(root, ["rev-parse", "--verify", "HEAD"], steps, "repo", "missing_head")
    add_step(steps, "repo", "ok", "repository has a HEAD commit")


def git_status_step(root: Path, steps: List[Dict[str, Any]], warnings: List[Dict[str, Any]]) -> None:
    code, out, err = run_git(root, ["status", "--short"])
    if code != 0:
        fail(steps, "git", "git_status_failed", "git status failed", {"error": short_error(err)})
    changed_count = len([line for line in out.splitlines() if line.strip()])
    if changed_count:
        warning = {"code": "working_tree_dirty", "changed_count": changed_count}
        warnings.append(warning)
        add_step(steps, "git", "warning", "working tree has uncommitted changes", warning)
        return
    add_step(steps, "git", "ok", "working tree status checked", {"changed_count": 0})


def build_map_plan(root: Path, worktree_path: Path, steps: List[Dict[str, Any]]) -> MapPlan:
    map_path = root / MAP_PATH
    if not map_path.exists():
        return MapPlan(path=map_path, exists=False, root=root, worktree_path=worktree_path, links=[])

    try:
        raw = json.loads(map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(steps, "worktree-map", "map_json_invalid", "worktree-map JSON is invalid", {"error": str(exc)})
    except OSError as exc:
        fail(steps, "worktree-map", "map_read_failed", "could not read worktree-map", {"error": str(exc)})

    if not isinstance(raw, Mapping):
        fail(steps, "worktree-map", "map_root_invalid", "worktree-map root must be an object")

    links_raw = raw.get("links", [])
    if not isinstance(links_raw, list):
        fail(steps, "worktree-map", "map_links_invalid", "worktree-map links must be a list")

    links: List[LinkPlan] = []
    for index, item in enumerate(links_raw):
        if not isinstance(item, Mapping):
            fail(steps, "worktree-map", "map_link_invalid", "worktree-map link must be an object", {"index": index})
        source = item.get("source")
        target = item.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            fail(
                steps,
                "worktree-map",
                "map_link_invalid",
                "worktree-map link must include string source and target",
                {"index": index},
            )
        if not source.strip() or not target.strip():
            fail(
                steps,
                "worktree-map",
                "map_link_invalid",
                "worktree-map source and target cannot be empty",
                {"index": index},
            )

        required = bool(item.get("required", False))
        source_path = safe_child(root, source, "source", "worktree-map", steps)
        target_path = safe_child(worktree_path, target, "target", "worktree-map", steps)
        source_exists = source_path.exists()
        should_link = source_exists
        if not source_exists and required:
            fail(
                steps,
                "worktree-map",
                "required_source_missing",
                "required worktree-map source is missing",
                {"source": source, "target": target},
            )
        if should_link and tracked_path_exists(root, target, steps):
            fail(
                steps,
                "worktree-map",
                "target_conflict",
                "worktree-map target already exists in HEAD",
                {"source": source, "target": target},
            )

        links.append(
            LinkPlan(
                source=source,
                target=target,
                required=required,
                description=str(item.get("description", "")),
                source_path=source_path,
                target_path=target_path,
                source_exists=source_exists,
                should_link=should_link,
            )
        )

    return MapPlan(path=map_path, exists=True, root=root, worktree_path=worktree_path, links=links)


def apply_worktree_map(
    map_plan: MapPlan,
    steps: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not map_plan.exists:
        add_step(steps, "worktree-map", "skipped", "worktree-map file is missing")
        return []
    if not map_plan.links:
        add_step(steps, "worktree-map", "skipped", "worktree-map has no links")
        return []

    results: List[Dict[str, Any]] = []
    for link in map_plan.links:
        if not link.should_link:
            result = link_result(link, "skipped", "optional source missing")
            results.append(result)
            warnings.append(
                {
                    "code": "optional_source_missing",
                    "source": link.source,
                    "target": link.target,
                }
            )
            continue

        source_resolved = link.source_path.resolve(strict=False)
        target_resolved = link.target_path.resolve(strict=False)
        ensure_within(source_resolved, map_plan.root, "source", "worktree-map", steps)
        ensure_within(target_resolved, map_plan.worktree_path, "target", "worktree-map", steps)

        if not link.source_path.exists():
            if link.required:
                fail(
                    steps,
                    "worktree-map",
                    "required_source_missing",
                    "required worktree-map source disappeared",
                    {"source": link.source, "target": link.target},
                )
            result = link_result(link, "skipped", "optional source missing")
            results.append(result)
            continue

        if os.path.lexists(str(link.target_path)):
            fail(
                steps,
                "worktree-map",
                "target_conflict",
                "worktree-map target already exists",
                {"source": link.source, "target": link.target},
            )

        try:
            link.target_path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(str(source_resolved), str(link.target_path))
        except OSError as exc:
            fail(
                steps,
                "worktree-map",
                "symlink_failed",
                "could not create worktree-map symlink",
                {"source": link.source, "target": link.target, "error": str(exc)},
            )
        results.append(link_result(link, "linked", "created symlink"))

    status = "warning" if any(item["status"] == "skipped" for item in results) else "ok"
    message = "applied worktree-map with warnings" if status == "warning" else "applied worktree-map"
    add_step(steps, "worktree-map", status, message, {"link_count": len(results)})
    return results


def final_validation(
    *,
    root: Path,
    exp_id: str,
    branch: str,
    exp_path: Path,
    outputs_path: Path,
    logs_path: Path,
    worktree_path: Path,
    manifest_path: Path,
    plan_path: Path,
    plan_written: bool,
    thread_id: str,
    link_results: Sequence[Mapping[str, Any]],
    steps: List[Dict[str, Any]],
) -> None:
    with ThreadPoolExecutor(max_workers=2) as executor:
        branch_future = executor.submit(branch_exists, root, branch)
        worktree_future = executor.submit(worktree_registered, root, worktree_path)

    checks = {
        "experiment_dir": exp_path.is_dir(),
        "outputs_dir": outputs_path.is_dir(),
        "logs_dir": logs_path.is_dir(),
        "worktree_dir": worktree_path.is_dir(),
        "branch_exists": branch_future.result(),
        "worktree_registered": worktree_future.result(),
        "manifest_exists": manifest_path.is_file(),
        "plan_state": plan_path.is_file() if plan_written else not plan_path.exists(),
        "worktree_map_applied": all(item.get("status") in {"linked", "skipped"} for item in link_results),
    }

    manifest = load_manifest_for_validation(manifest_path, steps)
    checks["manifest_id"] = manifest.get("id") == exp_id
    checks["manifest_branch"] = manifest.get("branch") == branch
    checks["manifest_agent"] = manifest.get("agent") == "codex"
    checks["session_state"] = session_recorded(manifest, thread_id) if thread_id else "sessions" not in manifest

    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        fail(
            steps,
            "final-validation",
            "validation_failed",
            "final validation failed",
            {"failed": failed},
        )
    add_step(steps, "final-validation", "ok", "validated initialized experiment", {"checks": checks})


def branch_exists(root: Path, branch: str) -> bool:
    code, _out, _err = run_git(root, ["show-ref", "--verify", "--quiet", "refs/heads/{0}".format(branch)])
    return code == 0


def worktree_registered(root: Path, worktree_path: Path) -> bool:
    code, out, _err = run_git(root, ["worktree", "list", "--porcelain"])
    if code != 0:
        return False
    expected = worktree_path.resolve(strict=False)
    for line in out.splitlines():
        if line.startswith("worktree ") and Path(line.removeprefix("worktree ")).resolve(strict=False) == expected:
            return True
    return False


def tracked_path_exists(root: Path, rel_path: str, steps: List[Dict[str, Any]]) -> bool:
    normalized = Path(rel_path).as_posix().strip("/")
    if not normalized:
        fail(steps, "worktree-map", "map_link_invalid", "worktree-map target cannot resolve to repository root")
    code, out, err = run_git(root, ["ls-tree", "-r", "--name-only", "HEAD", "--", normalized])
    if code != 0:
        fail(steps, "worktree-map", "git_ls_tree_failed", "could not inspect HEAD tree", {"error": short_error(err)})
    return any(line == normalized or line.startswith(normalized + "/") for line in out.splitlines())


def run_git_checked(
    root: Path,
    args: Sequence[str],
    steps: List[Dict[str, Any]],
    step: str,
    code_name: str,
) -> str:
    code, out, err = run_git(root, args)
    if code != 0:
        fail(steps, step, code_name, "git command failed", {"args": ["git"] + list(args), "error": short_error(err)})
    return out


def run_git(root: Path, args: Sequence[str]) -> Tuple[int, str, str]:
    env = os.environ.copy()
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(
            ["git"] + list(args),
            cwd=str(root),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def load_manifest_for_validation(path: Path, steps: List[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(steps, "final-validation", "manifest_json_invalid", "manifest.json is invalid", {"error": str(exc)})
    except OSError as exc:
        fail(steps, "final-validation", "manifest_read_failed", "could not read manifest.json", {"error": str(exc)})
    if not isinstance(raw, dict):
        fail(steps, "final-validation", "manifest_invalid", "manifest.json root must be an object")
    return raw


def session_recorded(manifest: Mapping[str, Any], thread_id: str) -> bool:
    sessions = manifest.get("sessions")
    if not isinstance(sessions, list):
        return False
    for item in sessions:
        if isinstance(item, Mapping) and item.get("id") == thread_id:
            return True
    return False


def safe_child(
    parent: Path,
    child: str,
    label: str,
    step: str,
    steps: List[Dict[str, Any]],
) -> Path:
    parent_resolved = parent.resolve(strict=False)
    child_path = (parent / child).resolve(strict=False)
    ensure_within(child_path, parent_resolved, label, step, steps)
    return child_path


def ensure_within(
    path: Path,
    parent: Path,
    label: str,
    step: str,
    steps: List[Dict[str, Any]],
) -> None:
    try:
        path.relative_to(parent.resolve(strict=False))
    except ValueError:
        fail(steps, step, "{0}_escapes_root".format(label), "{0} path escapes its root".format(label), {"path": path})


def write_json_file(
    path: Path,
    payload: Mapping[str, Any],
    steps: List[Dict[str, Any]],
    step: str,
) -> None:
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        fail(steps, step, "{0}_write_failed".format(step), "could not write {0}".format(path.name), {"error": str(exc)})


def link_result(link: LinkPlan, status: str, message: str) -> Dict[str, Any]:
    return {
        "source": link.source,
        "target": link.target,
        "required": link.required,
        "description": link.description,
        "status": status,
        "message": message,
    }


def add_step(
    steps: List[Dict[str, Any]],
    name: str,
    status: str,
    message: str,
    details: Optional[Mapping[str, Any]] = None,
) -> None:
    step: Dict[str, Any] = {"name": name, "status": status, "message": message}
    if details:
        step["details"] = json_safe(details)
    steps.append(step)


def fail(
    steps: List[Dict[str, Any]],
    step: str,
    code: str,
    message: str,
    details: Optional[Mapping[str, Any]] = None,
) -> None:
    add_step(steps, step, "error", message, details)
    raise InitExperimentError(message, code=code, step=step, steps=steps, details=details)


def print_json(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(json_safe(payload), indent=2, ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe(item) for item in value]
    return value


def short_error(text: str) -> str:
    return " ".join(text.strip().split())[:300]


def text_with_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def now_text() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
