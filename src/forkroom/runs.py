#!/usr/bin/env python3
"""Manage ForkRoom long-running task records."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .time_format import _parse_timestamp


EXPS_DIR = Path(".agents") / "exps"
RUNS_DIR = "runs"
RUN_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
RELATIVE_ETA_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*$", re.IGNORECASE)

PENDING_RUN_STATUS = "pending"
ACTIVE_RUN_STATUSES = {"pending", "running", "waiting"}
TERMINAL_RUN_STATUSES = {"succeeded", "failed", "canceled"}
RUN_STATUSES = ACTIVE_RUN_STATUSES | TERMINAL_RUN_STATUSES

ALLOWED_RUN_TRANSITIONS = {
    "pending": {"pending", "running", "waiting", "failed", "canceled"},
    "running": {"running", "waiting", "succeeded", "failed", "canceled"},
    "waiting": {"waiting", "running", "succeeded", "failed", "canceled"},
    "succeeded": set(),
    "failed": set(),
    "canceled": set(),
}


class RunError(Exception):
    """Raised when a run cannot be safely updated."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_payload(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": str(self),
                "details": json_safe(self.details),
            },
        }


def build_parser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Create and update tracked ForkRoom runs.",
    )
    subparsers = parser.add_subparsers(dest="action", metavar="ACTION", required=True)

    start = subparsers.add_parser("start", help="start a tracked run")
    add_common_run_args(start, require_run=True)
    start.add_argument("--title", required=True, help="Human-readable run title.")
    start.add_argument("--session-id", default="", help="Codex session id. Defaults to CODEX_THREAD_ID.")
    start.add_argument(
        "--status",
        choices=sorted(ACTIVE_RUN_STATUSES),
        default="running",
        help="Initial non-terminal status. Defaults to running.",
    )
    start.add_argument("--eta", required=True, help="Estimated end time as ISO timestamp or duration like 30m/2h.")
    start.add_argument("--completed", type=int, default=None, help="Completed item count.")
    start.add_argument("--total", type=int, default=None, help="Total item count.")
    start.add_argument("--message", default="", help="Progress message.")
    start.add_argument("--created-at", default="", help="Creation timestamp. Defaults to now.")

    update = subparsers.add_parser("update", help="update a non-terminal run")
    add_common_run_args(update, require_run=True)
    update.add_argument(
        "--status",
        choices=sorted(ACTIVE_RUN_STATUSES),
        default="",
        help="Updated non-terminal status. Defaults to the current status.",
    )
    update.add_argument("--eta", required=True, help="Estimated end time as ISO timestamp or duration like 30m/2h.")
    update.add_argument("--completed", type=int, default=None, help="Completed item count.")
    update.add_argument("--total", type=int, default=None, help="Total item count.")
    update.add_argument("--message", default="", help="Progress message.")
    update.add_argument("--updated-at", default="", help="Update timestamp. Defaults to now.")

    for action in ("succeed", "fail", "cancel"):
        finish = subparsers.add_parser(action, help="{0} a run".format(action))
        add_common_run_args(finish, require_run=True)
        finish.add_argument("--message", default="", help="Final message.")
        finish.add_argument("--updated-at", default="", help="Completion timestamp. Defaults to now.")
        if action == "fail":
            finish.add_argument("--error", default="", help="Optional error summary.")

    return parser


def add_common_run_args(parser: argparse.ArgumentParser, require_run: bool) -> None:
    parser.add_argument("--root", default=".", help="Repository root. Defaults to the current directory.")
    parser.add_argument("--exp", required=True, help="Experiment id under .agents/exps.")
    parser.add_argument("--id", required=require_run, help="Run id under the experiment runs directory.")


def main(argv: Optional[Sequence[str]] = None, prog: Optional[str] = None) -> int:
    args = build_parser(prog=prog).parse_args(argv)
    try:
        if args.action == "start":
            payload = start_run(
                root=Path(args.root),
                exp_id=args.exp,
                run_id=args.id,
                title=args.title,
                session_id=args.session_id or os.environ.get("CODEX_THREAD_ID", ""),
                status=args.status,
                eta=args.eta,
                completed=args.completed,
                total=args.total,
                message=args.message,
                created_at=args.created_at,
            )
        elif args.action == "update":
            payload = update_run(
                root=Path(args.root),
                exp_id=args.exp,
                run_id=args.id,
                status=args.status,
                eta=args.eta,
                completed=args.completed,
                total=args.total,
                message=args.message,
                updated_at=args.updated_at,
            )
        elif args.action == "succeed":
            payload = finish_run(
                root=Path(args.root),
                exp_id=args.exp,
                run_id=args.id,
                status="succeeded",
                message=args.message,
                updated_at=args.updated_at,
            )
        elif args.action == "fail":
            payload = finish_run(
                root=Path(args.root),
                exp_id=args.exp,
                run_id=args.id,
                status="failed",
                message=args.message,
                updated_at=args.updated_at,
                error=args.error,
            )
        else:
            payload = finish_run(
                root=Path(args.root),
                exp_id=args.exp,
                run_id=args.id,
                status="canceled",
                message=args.message,
                updated_at=args.updated_at,
            )
    except RunError as exc:
        print_json(exc.to_payload())
        return 1

    print_json(payload)
    return 0


def start_run(
    root: Path,
    exp_id: str,
    run_id: str,
    title: str,
    session_id: str,
    status: str = "running",
    eta: str = "",
    completed: Optional[int] = None,
    total: Optional[int] = None,
    message: str = "",
    created_at: str = "",
) -> Dict[str, Any]:
    root = resolve_root(root)
    exp_path = experiment_path(root, exp_id)
    run_id = validate_run_id(run_id)
    title = required_text(title, "title")
    session_id = required_text(session_id, "session-id")
    status = validate_status(status, allow_terminal=False)
    completed_value = validate_count(completed, "completed")
    total_value = validate_count(total, "total")
    validate_fraction(completed_value, total_value)
    timestamp = normalize_timestamp(created_at or now_text(), "created-at")
    estimated_end_at = parse_eta(eta, now=_parse_timestamp(timestamp) or datetime.now().astimezone())
    run_path = run_file_path(exp_path, run_id)

    if run_path.exists():
        raise RunError("run {0} already exists".format(run_id), code="run_exists", details={"path": run_path})

    active_owner = find_active_run_for_session(root, session_id)
    if active_owner is not None:
        active_exp, active_run, active_path = active_owner
        raise RunError(
            "session {0} already has an active run".format(session_id),
            code="active_session_run_exists",
            details={"session_id": session_id, "exp": active_exp, "run": active_run, "path": active_path},
        )

    run_path.parent.mkdir(parents=True, exist_ok=True)
    run = {
        "id": run_id,
        "title": title,
        "session_id": session_id,
        "status": status,
        "completed": completed_value,
        "total": total_value,
        "message": message.strip(),
        "estimated_end_at": estimated_end_at,
        "created_at": timestamp,
        "updated_at": timestamp,
        "started_at": timestamp,
        "ended_at": "",
        "events": [
            build_event(
                kind="start",
                status=status,
                completed=completed_value,
                total=total_value,
                message=message,
                estimated_end_at=estimated_end_at,
                updated_at=timestamp,
            )
        ],
    }
    write_json(run_path, run)
    touch_manifest(exp_path, timestamp)
    return ok_payload(run_path, run)


def update_run(
    root: Path,
    exp_id: str,
    run_id: str,
    status: str = "",
    eta: str = "",
    completed: Optional[int] = None,
    total: Optional[int] = None,
    message: str = "",
    updated_at: str = "",
) -> Dict[str, Any]:
    root = resolve_root(root)
    exp_path = experiment_path(root, exp_id)
    run_id = validate_run_id(run_id)
    run_path = run_file_path(exp_path, run_id)
    run = load_run(run_path)

    current_status = str(run.get("status", "")).strip()
    if current_status in TERMINAL_RUN_STATUSES:
        raise RunError("terminal run {0} cannot be updated".format(run_id), code="terminal_run")

    next_status = validate_status(status or current_status, allow_terminal=False)
    validate_transition(current_status, next_status)
    completed_value = validate_count(completed if completed is not None else run.get("completed"), "completed")
    total_value = validate_count(total if total is not None else run.get("total"), "total")
    validate_fraction(completed_value, total_value)
    timestamp = normalize_timestamp(updated_at or now_text(), "updated-at")
    estimated_end_at = parse_eta(eta, now=_parse_timestamp(timestamp) or datetime.now().astimezone())
    next_message = message.strip() if message.strip() else str(run.get("message", ""))

    run["status"] = next_status
    run["completed"] = completed_value
    run["total"] = total_value
    run["message"] = next_message
    run["estimated_end_at"] = estimated_end_at
    run["updated_at"] = timestamp
    ensure_event_list(run).append(
        build_event(
            kind="update",
            status=next_status,
            completed=completed_value,
            total=total_value,
            message=next_message,
            estimated_end_at=estimated_end_at,
            updated_at=timestamp,
        )
    )
    write_json(run_path, run)
    touch_manifest(exp_path, timestamp)
    return ok_payload(run_path, run)


def finish_run(
    root: Path,
    exp_id: str,
    run_id: str,
    status: str,
    message: str = "",
    updated_at: str = "",
    error: str = "",
) -> Dict[str, Any]:
    root = resolve_root(root)
    exp_path = experiment_path(root, exp_id)
    run_id = validate_run_id(run_id)
    status = validate_status(status, allow_terminal=True, terminal_only=True)
    run_path = run_file_path(exp_path, run_id)
    run = load_run(run_path)

    current_status = str(run.get("status", "")).strip()
    if current_status in TERMINAL_RUN_STATUSES:
        raise RunError("terminal run {0} cannot be updated".format(run_id), code="terminal_run")
    validate_transition(current_status, status)

    timestamp = normalize_timestamp(updated_at or now_text(), "updated-at")
    next_message = message.strip() if message.strip() else str(run.get("message", ""))
    existing_total = validate_count(run.get("total"), "total")
    completed_value = validate_count(run.get("completed"), "completed")
    if status == "succeeded" and existing_total is not None:
        completed_value = existing_total
    validate_fraction(completed_value, existing_total)

    run["status"] = status
    run["completed"] = completed_value
    run["total"] = existing_total
    run["message"] = next_message
    run["updated_at"] = timestamp
    run["ended_at"] = timestamp
    if error.strip():
        run["error"] = error.strip()
    ensure_event_list(run).append(
        build_event(
            kind=status,
            status=status,
            completed=completed_value,
            total=existing_total,
            message=next_message,
            estimated_end_at=str(run.get("estimated_end_at", "")),
            updated_at=timestamp,
            error=error.strip(),
        )
    )
    write_json(run_path, run)
    touch_manifest(exp_path, timestamp)
    return ok_payload(run_path, run)


def find_active_run_for_session(root: Path, session_id: str) -> Optional[Tuple[str, str, str]]:
    exps_path = root / EXPS_DIR
    if not exps_path.is_dir():
        return None
    for exp_path in sorted(path for path in exps_path.iterdir() if path.is_dir()):
        runs_path = exp_path / RUNS_DIR
        if not runs_path.is_dir():
            continue
        for run_path in sorted(runs_path.glob("*.json")):
            try:
                run = load_json(run_path)
            except RunError:
                continue
            if not isinstance(run, Mapping):
                continue
            if str(run.get("session_id", "")).strip() != session_id:
                continue
            if str(run.get("status", "")).strip() in ACTIVE_RUN_STATUSES:
                return exp_path.name, str(run.get("id", run_path.stem)), str(run_path)
    return None


def validate_run_events(run_id: str, data: Mapping[str, Any]) -> List[str]:
    warnings: List[str] = []
    status = str(data.get("status", "")).strip()
    if status not in RUN_STATUSES:
        warnings.append("run {0}: invalid status {1}".format(run_id, status or "<empty>"))
    if status in ACTIVE_RUN_STATUSES and not str(data.get("estimated_end_at", "")).strip():
        warnings.append("run {0}: non-terminal status requires estimated_end_at".format(run_id))
    if status in TERMINAL_RUN_STATUSES and not str(data.get("ended_at", "")).strip():
        warnings.append("run {0}: terminal status should include ended_at".format(run_id))

    completed = validate_count_value(data.get("completed"))
    total = validate_count_value(data.get("total"))
    if data.get("completed") is not None and completed is None:
        warnings.append("run {0}: completed must be a non-negative integer".format(run_id))
    if data.get("total") is not None and total is None:
        warnings.append("run {0}: total must be a non-negative integer".format(run_id))
    if completed is not None and total is not None and completed > total:
        warnings.append("run {0}: completed cannot exceed total".format(run_id))

    raw_events = data.get("events")
    if raw_events is None:
        warnings.append("run {0}: events is missing".format(run_id))
        return warnings
    if not isinstance(raw_events, list):
        warnings.append("run {0}: events must be a list".format(run_id))
        return warnings

    previous_status = ""
    terminal_seen = False
    last_event_status = ""
    for index, event in enumerate(raw_events):
        if not isinstance(event, Mapping):
            warnings.append("run {0}: events[{1}] must be an object".format(run_id, index))
            continue
        event_status = str(event.get("status", "")).strip()
        if event_status not in RUN_STATUSES:
            warnings.append("run {0}: events[{1}] has invalid status {2}".format(run_id, index, event_status or "<empty>"))
            continue
        if terminal_seen:
            warnings.append("run {0}: events[{1}] occurs after terminal status".format(run_id, index))
        if event_status in ACTIVE_RUN_STATUSES and not str(event.get("estimated_end_at", "")).strip():
            warnings.append("run {0}: events[{1}] non-terminal status requires estimated_end_at".format(run_id, index))
        if previous_status and not transition_allowed(previous_status, event_status):
            warnings.append(
                "run {0}: invalid transition {1}->{2} at events[{3}]".format(
                    run_id,
                    previous_status,
                    event_status,
                    index,
                )
            )
        event_completed = validate_count_value(event.get("completed"))
        event_total = validate_count_value(event.get("total"))
        if event.get("completed") is not None and event_completed is None:
            warnings.append("run {0}: events[{1}] completed must be a non-negative integer".format(run_id, index))
        if event.get("total") is not None and event_total is None:
            warnings.append("run {0}: events[{1}] total must be a non-negative integer".format(run_id, index))
        if event_completed is not None and event_total is not None and event_completed > event_total:
            warnings.append("run {0}: events[{1}] completed cannot exceed total".format(run_id, index))
        previous_status = event_status
        last_event_status = event_status
        terminal_seen = event_status in TERMINAL_RUN_STATUSES

    if last_event_status and status in RUN_STATUSES and last_event_status != status:
        warnings.append("run {0}: latest event status {1} does not match current status {2}".format(run_id, last_event_status, status))
    return warnings


def transition_allowed(current: str, next_status: str) -> bool:
    if not current:
        return next_status in ACTIVE_RUN_STATUSES
    return next_status in ALLOWED_RUN_TRANSITIONS.get(current, set())


def validate_transition(current: str, next_status: str) -> None:
    if not transition_allowed(current, next_status):
        raise RunError(
            "invalid run status transition {0}->{1}".format(current or "<none>", next_status),
            code="invalid_transition",
            details={"current": current, "next": next_status},
        )


def build_event(
    kind: str,
    status: str,
    completed: Optional[int],
    total: Optional[int],
    message: str,
    estimated_end_at: str,
    updated_at: str,
    error: str = "",
) -> Dict[str, Any]:
    event: Dict[str, Any] = {
        "type": kind,
        "status": status,
        "completed": completed,
        "total": total,
        "message": message.strip(),
        "estimated_end_at": estimated_end_at,
        "updated_at": updated_at,
    }
    if error:
        event["error"] = error
    return event


def ensure_event_list(run: Dict[str, Any]) -> List[Any]:
    raw_events = run.get("events")
    if raw_events is None:
        raw_events = []
        run["events"] = raw_events
    if not isinstance(raw_events, list):
        raise RunError("run events must be a list", code="invalid_events")
    return raw_events


def ok_payload(path: Path, run: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "run": json_safe(run),
        "path": str(path),
    }


def resolve_root(root: Path) -> Path:
    root = root.expanduser().resolve(strict=False)
    if not root.exists():
        raise RunError("root does not exist", code="root_missing", details={"root": root})
    return root


def experiment_path(root: Path, exp_id: str) -> Path:
    exp_id = required_text(exp_id, "exp")
    exps_path = root / EXPS_DIR
    exp_path = safe_child(exps_path, exp_id, "experiment")
    manifest_path = exp_path / "manifest.json"
    if not manifest_path.exists():
        raise RunError("manifest.json is missing for experiment {0}".format(exp_id), code="experiment_missing")
    return exp_path


def run_file_path(exp_path: Path, run_id: str) -> Path:
    return safe_child(exp_path / RUNS_DIR, "{0}.json".format(run_id), "run")


def validate_run_id(run_id: str) -> str:
    run_id = required_text(run_id, "id")
    if not RUN_ID_RE.match(run_id):
        raise RunError("id must be lowercase alphanumeric words separated by hyphens", code="invalid_id")
    return run_id


def validate_status(status: str, allow_terminal: bool, terminal_only: bool = False) -> str:
    status = required_text(status, "status")
    allowed = TERMINAL_RUN_STATUSES if terminal_only else RUN_STATUSES if allow_terminal else ACTIVE_RUN_STATUSES
    if status not in allowed:
        raise RunError("invalid status {0}".format(status), code="invalid_status", details={"status": status})
    return status


def validate_count(value: Any, label: str) -> Optional[int]:
    if value is None:
        return None
    count = validate_count_value(value)
    if count is None:
        raise RunError("{0} must be a non-negative integer".format(label), code="invalid_{0}".format(label))
    return count


def validate_count_value(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        count = int(value)
    except (TypeError, ValueError):
        return None
    if count < 0:
        return None
    return count


def validate_fraction(completed: Optional[int], total: Optional[int]) -> None:
    if completed is not None and total is not None and completed > total:
        raise RunError("completed cannot exceed total", code="invalid_fraction")


def parse_eta(value: str, now: Optional[datetime] = None) -> str:
    value = required_text(value, "eta")
    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc).astimezone()
    match = RELATIVE_ETA_RE.match(value)
    if match:
        amount = float(match.group(1))
        unit = match.group(2).lower()
        seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        return iso_text(current + timedelta(seconds=seconds))

    parsed = _parse_timestamp(value)
    if parsed is None:
        raise RunError("eta must be an ISO timestamp or a duration like 30m/2h", code="invalid_eta")
    return iso_text(parsed)


def normalize_timestamp(value: str, label: str) -> str:
    value = required_text(value, label)
    parsed = _parse_timestamp(value)
    if parsed is None:
        raise RunError("{0} must be an ISO timestamp".format(label), code="invalid_timestamp", details={"field": label})
    return iso_text(parsed)


def now_text() -> str:
    return iso_text(datetime.now().astimezone())


def iso_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().replace(microsecond=0).isoformat()


def load_run(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise RunError("run file is missing", code="run_missing", details={"path": path})
    raw = load_json(path)
    if not isinstance(raw, dict):
        raise RunError("run file root must be an object", code="invalid_run", details={"path": path})
    return raw


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunError("run JSON is invalid: {0}".format(exc), code="invalid_json", details={"path": path}) from exc
    except OSError as exc:
        raise RunError("run JSON could not be read: {0}".format(exc), code="read_failed", details={"path": path}) from exc


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(".{0}.tmp".format(path.name))
    try:
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(str(temp_path), str(path))
    except OSError as exc:
        raise RunError("could not write run JSON: {0}".format(exc), code="write_failed", details={"path": path}) from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def touch_manifest(exp_path: Path, updated_at: str) -> None:
    manifest_path = exp_path / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RunError("manifest.json could not be read: {0}".format(exc), code="manifest_read_failed") from exc
    if not isinstance(manifest, dict):
        raise RunError("manifest.json root must be an object", code="manifest_invalid")
    manifest["updated_at"] = updated_at
    temp_path = manifest_path.with_name(".manifest.json.tmp")
    try:
        temp_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(str(temp_path), str(manifest_path))
    except OSError as exc:
        raise RunError("manifest.json could not be written: {0}".format(exc), code="manifest_write_failed") from exc
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def required_text(value: str, label: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise RunError("{0} is required".format(label), code="missing_{0}".format(label.replace("-", "_")))
    return value


def safe_child(parent: Path, child_name: str, label: str) -> Path:
    child = (parent / child_name).resolve(strict=False)
    try:
        child.relative_to(parent.resolve(strict=False))
    except ValueError as exc:
        raise RunError("{0} path escapes {1}".format(label, parent), code="path_escape") from exc
    return child


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


def print_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(json_safe(payload), indent=2, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
