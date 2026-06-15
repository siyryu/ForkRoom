import json
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote

from .models import AgentSession, Experiment, LinkRule, LinkStatus, MapConfig, Snapshot


EXPS_DIR = Path(".agents") / "exps"
MAP_PATH = Path(".vibe-board") / "worktree-map.json"


def scan_repository(root: Path) -> Snapshot:
    root = root.resolve()
    map_config = load_map_config(root)
    registered_worktrees, git_error = load_registered_worktrees(root)
    branches = load_branches(root) if git_error is None else set()
    experiments = load_experiments(root, map_config.links, registered_worktrees, branches)
    return Snapshot(
        root=root,
        exps_path=root / EXPS_DIR,
        map_config=map_config,
        experiments=experiments,
        git_error=git_error,
    )


def load_map_config(root: Path) -> MapConfig:
    path = root / MAP_PATH
    if not path.exists():
        return MapConfig(path=path, exists=False, version=None, links=[])

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return MapConfig(path=path, exists=True, version=None, links=[], error=str(exc))

    if not isinstance(raw, Mapping):
        return MapConfig(path=path, exists=True, version=None, links=[], error="Config root is not an object.")

    version = raw.get("version")
    links_raw = raw.get("links", [])
    if not isinstance(links_raw, list):
        return MapConfig(path=path, exists=True, version=_safe_int(version), links=[], error="links must be a list.")

    links: List[LinkRule] = []
    errors: List[str] = []
    for index, item in enumerate(links_raw):
        if not isinstance(item, Mapping):
            errors.append("links[{0}] is not an object".format(index))
            continue
        source = item.get("source")
        target = item.get("target")
        if not isinstance(source, str) or not isinstance(target, str):
            errors.append("links[{0}] must include string source and target".format(index))
            continue
        links.append(
            LinkRule(
                source=source,
                target=target,
                required=bool(item.get("required", False)),
                description=str(item.get("description", "")),
            )
        )

    return MapConfig(
        path=path,
        exists=True,
        version=_safe_int(version),
        links=links,
        error="; ".join(errors) if errors else None,
    )


def load_experiments(
    root: Path,
    links: Sequence[LinkRule],
    registered_worktrees: Set[Path],
    branches: Set[str],
) -> List[Experiment]:
    exps_path = root / EXPS_DIR
    if not exps_path.exists():
        return []

    experiments: List[Experiment] = []
    for exp_path in sorted((path for path in exps_path.iterdir() if path.is_dir()), key=lambda item: item.name):
        experiments.append(load_experiment(root, exp_path, links, registered_worktrees, branches))
    experiments.sort(key=experiment_updated_sort_key)
    return with_session_ownership_warnings(experiments)


def experiment_updated_sort_key(experiment: Experiment) -> Tuple[bool, float, str]:
    updated_timestamp = _timestamp_value(experiment.updated_at)
    return (updated_timestamp is None, -(updated_timestamp or 0), experiment.id)


def load_experiment(
    root: Path,
    exp_path: Path,
    links: Sequence[LinkRule],
    registered_worktrees: Set[Path],
    branches: Set[str],
) -> Experiment:
    exp_id = exp_path.name
    manifest_path = exp_path / "manifest.json"
    manifest, manifest_error = load_manifest(manifest_path)
    warnings: List[str] = []
    if manifest_error:
        warnings.append(manifest_error)

    title = _string_value(manifest, "title", exp_id)
    status = _string_value(manifest, "status", "unknown")
    branch = _string_value(manifest, "branch", "agents/{0}".format(exp_id))
    created_at = _string_value(manifest, "created_at", _mtime_text(manifest_path if manifest_path.exists() else exp_path))
    updated_at = _string_value(manifest, "updated_at", _mtime_text(manifest_path if manifest_path.exists() else exp_path))
    summary = _string_value(manifest, "summary", "")
    agent = _string_value(manifest, "agent", "")
    sessions = load_sessions(manifest, warnings, default_agent=agent)

    worktree_path = exp_path / "worktree"
    worktree_exists = worktree_path.exists()
    normalized_worktree_path = worktree_path.resolve(strict=False)
    worktree_registered = normalized_worktree_path in registered_worktrees
    branch_exists = branch in branches

    if not manifest_path.exists():
        warnings.append("manifest.json is missing")
    if not worktree_exists:
        warnings.append("worktree directory is missing")
    if branch and not branch_exists:
        warnings.append("branch is missing")

    link_statuses = [inspect_link(root, worktree_path, rule) for rule in links]

    return Experiment(
        id=exp_id,
        title=title,
        status=status,
        branch=branch,
        created_at=created_at,
        updated_at=updated_at,
        summary=summary,
        agent=agent,
        path=exp_path,
        worktree_path=worktree_path,
        worktree_exists=worktree_exists,
        worktree_registered=worktree_registered,
        branch_exists=branch_exists,
        plan_summary=read_plan_summary(exp_path / "plan.md"),
        handoff_exists=(exp_path / "handoff.md").exists(),
        outputs_exists=(exp_path / "outputs").is_dir(),
        logs_exists=(exp_path / "logs").is_dir(),
        sessions=sessions,
        warnings=warnings,
        link_statuses=link_statuses,
    )


def load_sessions(manifest: Mapping[str, Any], warnings: List[str], default_agent: str = "") -> List[AgentSession]:
    raw_sessions = raw_manifest_sessions(manifest)
    if raw_sessions is None:
        return []
    if not isinstance(raw_sessions, list):
        warnings.append("sessions must be a list")
        return []

    sessions: List[AgentSession] = []
    seen_ids: Set[str] = set()
    for index, item in enumerate(raw_sessions):
        session = parse_session(item, index, warnings, default_agent)
        if session is None:
            continue
        if session.id in seen_ids:
            warnings.append("session {0} is listed more than once".format(session.id))
            continue
        seen_ids.add(session.id)
        sessions.append(session)
    return sessions


def raw_manifest_sessions(manifest: Mapping[str, Any]) -> Optional[Any]:
    if "sessions" in manifest:
        return manifest.get("sessions")
    if "session" in manifest:
        return [manifest.get("session")]
    if "session_id" in manifest:
        return [
            {
                "id": manifest.get("session_id"),
                "title": manifest.get("session_title", ""),
                "deeplink": manifest.get("session_deeplink", ""),
            }
        ]
    return None


def parse_session(
    item: Any,
    index: int,
    warnings: List[str],
    default_agent: str,
) -> Optional[AgentSession]:
    if isinstance(item, str):
        session_id = item.strip()
        if not session_id:
            warnings.append("sessions[{0}] is empty".format(index))
            return None
        return AgentSession(
            id=session_id,
            title=session_id,
            agent=default_agent,
            status="",
            created_at="",
            updated_at="",
            deeplink=codex_thread_deeplink(session_id),
        )

    if not isinstance(item, Mapping):
        warnings.append("sessions[{0}] must be a string or object".format(index))
        return None

    session_id = _first_string(item, ("id", "session_id", "thread_id"))
    if not session_id:
        warnings.append("sessions[{0}] must include id, session_id, or thread_id".format(index))
        return None

    deeplink = _first_string(item, ("deeplink", "deep_link", "url"))
    return AgentSession(
        id=session_id,
        title=_first_string(item, ("title", "name")) or session_id,
        agent=_first_string(item, ("agent",)) or default_agent,
        status=_first_string(item, ("status",)),
        created_at=_first_string(item, ("created_at", "started_at")),
        updated_at=_first_string(item, ("updated_at", "last_active_at")),
        deeplink=deeplink or codex_thread_deeplink(session_id),
        origin=_first_string(item, ("origin", "source")),
    )


def codex_thread_deeplink(session_id: str) -> str:
    return "codex://threads/{0}".format(quote(session_id, safe=""))


def with_session_ownership_warnings(experiments: List[Experiment]) -> List[Experiment]:
    owners: Dict[str, List[str]] = {}
    for experiment in experiments:
        for session in experiment.sessions:
            owners.setdefault(session.id, []).append(experiment.id)

    duplicate_owners = {
        session_id: sorted(set(exp_ids))
        for session_id, exp_ids in owners.items()
        if len(set(exp_ids)) > 1
    }
    if not duplicate_owners:
        return experiments

    updated: List[Experiment] = []
    for experiment in experiments:
        warnings = list(experiment.warnings)
        for session in experiment.sessions:
            exp_ids = duplicate_owners.get(session.id)
            if exp_ids:
                warnings.append(
                    "session {0} is also recorded by experiment(s): {1}; a session can only belong to one experiment".format(
                        session.id,
                        ", ".join(exp_id for exp_id in exp_ids if exp_id != experiment.id),
                    )
                )
        updated.append(replace(experiment, warnings=warnings))
    return updated


def inspect_link(root: Path, worktree_path: Path, rule: LinkRule) -> LinkStatus:
    source_path = root / rule.source
    target_path = worktree_path / rule.target

    source_safe = is_within(source_path.resolve(strict=False), root.resolve(strict=False))
    target_safe = is_within(target_path.resolve(strict=False), worktree_path.resolve(strict=False))
    if not source_safe:
        return LinkStatus(rule, "error", "source escapes repository root", False, False, False, False)
    if not target_safe:
        return LinkStatus(rule, "error", "target escapes worktree root", False, False, False, False)

    source_exists = source_path.exists()
    target_exists = os.path.lexists(str(target_path))
    target_is_symlink = target_path.is_symlink()
    points_to_expected = False

    if target_is_symlink:
        try:
            raw_target = os.readlink(str(target_path))
            linked_path = Path(raw_target)
            if not linked_path.is_absolute():
                linked_path = target_path.parent / linked_path
            points_to_expected = linked_path.resolve(strict=False) == source_path.resolve(strict=False)
        except OSError:
            points_to_expected = False

    if not source_exists:
        severity = "error" if rule.required else "warning"
        return LinkStatus(rule, severity, "source missing", source_exists, target_exists, target_is_symlink, points_to_expected)
    if not target_exists:
        return LinkStatus(rule, "warning", "target missing", source_exists, target_exists, target_is_symlink, points_to_expected)
    if not target_is_symlink:
        return LinkStatus(rule, "error", "target is not a symlink", source_exists, target_exists, target_is_symlink, points_to_expected)
    if not points_to_expected:
        return LinkStatus(rule, "error", "symlink points elsewhere", source_exists, target_exists, target_is_symlink, points_to_expected)
    return LinkStatus(rule, "ok", "linked", source_exists, target_exists, target_is_symlink, points_to_expected)


def load_manifest(path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    if not path.exists():
        return {}, None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {}, "manifest.json is invalid: {0}".format(exc)
    if not isinstance(raw, dict):
        return {}, "manifest.json root is not an object"
    return raw, None


def read_plan_summary(path: Path) -> str:
    if not path.exists():
        return "plan.md is missing"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return "plan.md could not be read: {0}".format(exc)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "plan.md is empty"
    summary = " ".join(lines[:4])
    return summary[:600]


def load_registered_worktrees(root: Path) -> Tuple[Set[Path], Optional[str]]:
    code, out, err = run_git(["worktree", "list", "--porcelain"], root)
    if code != 0:
        return set(), err.strip() or "git worktree list failed"

    paths: Set[Path] = set()
    for line in out.splitlines():
        if line.startswith("worktree "):
            paths.add(Path(line.removeprefix("worktree ")).resolve(strict=False))
    return paths, None


def load_branches(root: Path) -> Set[str]:
    code, out, _err = run_git(["branch", "--format=%(refname:short)"], root)
    if code != 0:
        return set()
    return {line.strip() for line in out.splitlines() if line.strip()}


def run_git(args: Sequence[str], cwd: Path) -> Tuple[int, str, str]:
    try:
        env = os.environ.copy()
        env["GIT_OPTIONAL_LOCKS"] = "0"
        completed = subprocess.run(
            ["git"] + list(args),
            cwd=str(cwd),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        return 1, "", str(exc)
    return completed.returncode, completed.stdout, completed.stderr


def is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _string_value(data: Mapping[str, Any], key: str, default: str) -> str:
    value = data.get(key, default)
    return value if isinstance(value, str) else str(value)


def _first_string(data: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value
        else:
            return str(value)
    return ""


def _timestamp_value(value: str) -> Optional[float]:
    text = value.strip()
    if not text:
        return None

    try:
        return float(text)
    except ValueError:
        pass

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _mtime_text(path: Path) -> str:
    try:
        return str(int(path.stat().st_mtime))
    except OSError:
        return ""
