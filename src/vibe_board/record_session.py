#!/usr/bin/env python3
"""Record a Codex thread on a Vibe Board experiment manifest."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from urllib.parse import quote


EXPS_DIR = Path(".agents") / "exps"


class RecordSessionError(Exception):
    """Raised when a session cannot be safely recorded."""


def build_parser(prog: Optional[str] = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Record a Codex session in .agents/exps/<exp-id>/manifest.json.",
    )
    parser.add_argument("--root", default=".", help="Repository root. Defaults to the current directory.")
    parser.add_argument("--exp", required=True, help="Experiment id under .agents/exps.")
    parser.add_argument("--thread-id", required=True, help="Codex thread/session id.")
    parser.add_argument("--title", default="", help="Human-readable session title.")
    parser.add_argument("--agent", default="codex", help="Session agent name. Defaults to codex.")
    parser.add_argument("--status", default="running", help="Session status. Defaults to running.")
    parser.add_argument("--created-at", default="", help="Session created_at timestamp. Defaults to now.")
    parser.add_argument("--updated-at", default="", help="Session updated_at timestamp. Defaults to now.")
    parser.add_argument("--deeplink", default="", help="Session deeplink. Defaults to codex://threads/<thread-id>.")
    parser.add_argument("--origin", default="", help="Optional source/origin label.")
    return parser


def main(argv: Optional[Sequence[str]] = None, prog: Optional[str] = None) -> int:
    args = build_parser(prog=prog).parse_args(argv)
    try:
        manifest_path = record_session(
            root=Path(args.root),
            exp_id=args.exp,
            thread_id=args.thread_id,
            title=args.title,
            agent=args.agent,
            status=args.status,
            created_at=args.created_at,
            updated_at=args.updated_at,
            deeplink=args.deeplink,
            origin=args.origin,
        )
    except RecordSessionError as exc:
        print("record-session: {0}".format(exc), file=sys.stderr)
        return 1

    print("recorded session {0} in {1}".format(args.thread_id.strip(), manifest_path))
    return 0


def record_session(
    root: Path,
    exp_id: str,
    thread_id: str,
    title: str = "",
    agent: str = "codex",
    status: str = "running",
    created_at: str = "",
    updated_at: str = "",
    deeplink: str = "",
    origin: str = "",
) -> Path:
    root = root.expanduser().resolve()
    exp_id = required_text(exp_id, "exp")
    thread_id = required_text(thread_id, "thread-id")

    exps_path = root / EXPS_DIR
    exp_path = safe_child(exps_path, exp_id, "experiment")
    manifest_path = exp_path / "manifest.json"
    if not manifest_path.exists():
        raise RecordSessionError("manifest.json is missing for experiment {0}".format(exp_id))

    duplicate_owner = find_existing_owner(exps_path, exp_id, thread_id)
    if duplicate_owner is not None:
        raise RecordSessionError(
            "session {0} is already recorded by experiment {1}".format(thread_id, duplicate_owner)
        )

    manifest = load_manifest(manifest_path)
    now = now_text()
    session = build_session(
        thread_id=thread_id,
        title=title,
        agent=agent,
        status=status,
        created_at=created_at or now,
        updated_at=updated_at or now,
        deeplink=deeplink,
        origin=origin,
    )

    changed = upsert_session(manifest, session)
    manifest["updated_at"] = session["updated_at"]
    if changed:
        write_manifest(manifest_path, manifest)
    return manifest_path


def build_session(
    thread_id: str,
    title: str,
    agent: str,
    status: str,
    created_at: str,
    updated_at: str,
    deeplink: str,
    origin: str,
) -> Dict[str, str]:
    session = {
        "id": thread_id,
        "title": title.strip() or thread_id,
        "agent": agent.strip() or "codex",
        "status": status.strip() or "running",
        "created_at": created_at.strip(),
        "updated_at": updated_at.strip(),
        "deeplink": deeplink.strip() or codex_thread_deeplink(thread_id),
    }
    if origin.strip():
        session["origin"] = origin.strip()
    return session


def upsert_session(manifest: Dict[str, Any], session: Mapping[str, str]) -> bool:
    raw_sessions = manifest.get("sessions")
    if raw_sessions is None:
        manifest["sessions"] = [dict(session)]
        return True
    if not isinstance(raw_sessions, list):
        raise RecordSessionError("manifest sessions must be a list")

    session_id = session["id"]
    matched = False
    deduped_sessions: List[Any] = []
    for item in raw_sessions:
        item_id = session_id_from_item(item)
        if item_id != session_id:
            deduped_sessions.append(item)
            continue
        if not matched:
            deduped_sessions.append(merged_session(item, session))
            matched = True

    if not matched:
        deduped_sessions.append(dict(session))

    manifest["sessions"] = deduped_sessions
    return True


def merged_session(existing: Any, incoming: Mapping[str, str]) -> Dict[str, Any]:
    if isinstance(existing, Mapping):
        merged = {str(key): value for key, value in existing.items()}
    else:
        merged = {}

    if not str(merged.get("created_at", "")).strip():
        merged["created_at"] = incoming["created_at"]

    for key, value in incoming.items():
        if key == "created_at" and str(merged.get("created_at", "")).strip():
            continue
        merged[key] = value
    return merged


def find_existing_owner(exps_path: Path, current_exp_id: str, thread_id: str) -> Optional[str]:
    if not exps_path.is_dir():
        return None

    for exp_path in sorted(path for path in exps_path.iterdir() if path.is_dir()):
        if exp_path.name == current_exp_id:
            continue
        manifest_path = exp_path / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = load_manifest(manifest_path)
        except RecordSessionError:
            continue
        for item in iter_session_items(manifest):
            if session_id_from_item(item) == thread_id:
                return exp_path.name
    return None


def iter_session_items(manifest: Mapping[str, Any]) -> Iterable[Any]:
    raw_sessions = manifest.get("sessions")
    if isinstance(raw_sessions, list):
        yield from raw_sessions
    if "session" in manifest:
        yield manifest.get("session")
    if "session_id" in manifest:
        yield {"id": manifest.get("session_id")}


def session_id_from_item(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if not isinstance(item, Mapping):
        return ""
    for key in ("id", "session_id", "thread_id"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def load_manifest(path: Path) -> Dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RecordSessionError("manifest.json is invalid: {0}".format(exc)) from exc
    except OSError as exc:
        raise RecordSessionError("manifest.json could not be read: {0}".format(exc)) from exc
    if not isinstance(raw, dict):
        raise RecordSessionError("manifest.json root must be an object")
    return raw


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    try:
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as exc:
        raise RecordSessionError("manifest.json could not be written: {0}".format(exc)) from exc


def codex_thread_deeplink(thread_id: str) -> str:
    return "codex://threads/{0}".format(quote(thread_id, safe=""))


def now_text() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def required_text(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise RecordSessionError("{0} is required".format(label))
    return value


def safe_child(parent: Path, child_name: str, label: str) -> Path:
    child = (parent / child_name).resolve(strict=False)
    try:
        child.relative_to(parent.resolve(strict=False))
    except ValueError as exc:
        raise RecordSessionError("{0} path escapes {1}".format(label, parent)) from exc
    return child


if __name__ == "__main__":
    raise SystemExit(main())
