import hashlib
import json
import os
import subprocess
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import quote

from .models import AgentSession, Experiment, LinkRule, LinkStatus, MapConfig, ProjectSnapshot, Run, Snapshot
from .runs import ACTIVE_RUN_STATUSES, validate_count_value, validate_run_events


EXPS_DIR = Path(".forkroom") / "exps"
MAP_PATH = Path(".forkroom") / "worktree-map.json"


def scan_repository(root: Path) -> Snapshot:
    return scan_repositories([root])


def scan_repositories(roots: Sequence[Path]) -> Snapshot:
    resolved_roots = normalize_roots(roots)
    project_names = project_display_names(resolved_roots)
    with ThreadPoolExecutor(max_workers=max(1, min(8, len(resolved_roots)))) as executor:
        futures = [
            executor.submit(scan_project, root, project_key_for_root(root), project_names[root])
            for root in resolved_roots
        ]

    projects: List[ProjectSnapshot] = []
    experiments: List[Experiment] = []
    for future in futures:
        project, project_experiments = future.result()
        projects.append(project)
        experiments.extend(project_experiments)

    experiments.sort(key=experiment_updated_sort_key)
    experiments = with_active_run_ownership_warnings(with_session_ownership_warnings(experiments))
    primary = projects[0]
    return Snapshot(
        root=primary.root,
        exps_path=primary.exps_path,
        map_config=primary.map_config,
        experiments=experiments,
        git_error=primary.git_error,
        roots=resolved_roots,
        projects=projects,
    )


def scan_project(root: Path, project_key: str, project_name: str) -> Tuple[ProjectSnapshot, List[Experiment]]:
    root = root.expanduser().resolve(strict=False)
    with ThreadPoolExecutor(max_workers=3) as executor:
        map_future = executor.submit(load_map_config, root)
        worktrees_future = executor.submit(load_registered_worktrees, root)
        branches_future = executor.submit(load_branches, root)
    
    map_config = map_future.result()
    registered_worktrees, git_error = worktrees_future.result()
    branches = branches_future.result() if git_error is None else set()
    project = ProjectSnapshot(
        key=project_key,
        name=project_name,
        root=root,
        exps_path=root / EXPS_DIR,
        map_config=map_config,
        git_error=git_error,
    )
    experiments = load_experiments(
        root,
        map_config.links,
        registered_worktrees,
        branches,
        project_key=project_key,
        project_name=project_name,
        include_session_ownership_warnings=False,
    )
    return project, experiments


def normalize_roots(roots: Sequence[Path]) -> List[Path]:
    requested_roots = list(roots) or [Path(".")]
    normalized: List[Path] = []
    seen: Set[Path] = set()
    for root in requested_roots:
        resolved = root.expanduser().resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        normalized.append(resolved)
    return normalized


def project_key_for_root(root: Path) -> str:
    return hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]


def project_display_names(roots: Sequence[Path]) -> Dict[Path, str]:
    groups: Dict[str, List[Path]] = {}
    for root in roots:
        groups.setdefault(root.name or str(root), []).append(root)

    names: Dict[Path, str] = {}
    for basename, group in groups.items():
        if len(group) == 1:
            names[group[0]] = basename
            continue
        names.update(shortest_unique_suffixes(group))
    return names


def shortest_unique_suffixes(roots: Sequence[Path]) -> Dict[Path, str]:
    max_len = max(len(root.parts) for root in roots)
    for length in range(1, max_len + 1):
        candidates = {root: "/".join(root.parts[-length:]) or str(root) for root in roots}
        if len(set(candidates.values())) == len(roots):
            return candidates
    return {root: str(root) for root in roots}


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
    project_key: str = "",
    project_name: str = "",
    include_session_ownership_warnings: bool = True,
) -> List[Experiment]:
    exps_path = root / EXPS_DIR
    if not exps_path.exists():
        return []

    project_key = project_key or project_key_for_root(root.resolve(strict=False))
    project_name = project_name or root.resolve(strict=False).name or str(root.resolve(strict=False))
    experiments: List[Experiment] = []
    for exp_path in (path for path in exps_path.iterdir() if path.is_dir()):
        experiments.append(
            load_experiment(
                root,
                exp_path,
                links,
                registered_worktrees,
                branches,
                project_key=project_key,
                project_name=project_name,
            )
        )
    experiments.sort(key=experiment_updated_sort_key)
    if include_session_ownership_warnings:
        return with_active_run_ownership_warnings(with_session_ownership_warnings(experiments))
    return experiments


def experiment_updated_sort_key(experiment: Experiment) -> Tuple[bool, float, str]:
    updated_timestamp = _timestamp_value(experiment.updated_at)
    return (updated_timestamp is None, -(updated_timestamp or 0), experiment.id)


def load_experiment(
    root: Path,
    exp_path: Path,
    links: Sequence[LinkRule],
    registered_worktrees: Set[Path],
    branches: Set[str],
    project_key: str,
    project_name: str,
) -> Experiment:
    exp_id = exp_path.name
    manifest_path = exp_path / "manifest.json"
    manifest_exists = manifest_path.exists()
    manifest, manifest_error = load_manifest(manifest_path)
    warnings: List[str] = []
    if manifest_error:
        warnings.append(manifest_error)

    title = _string_value(manifest, "title", exp_id)
    status = _string_value(manifest, "status", "unknown")
    branch = _string_value(manifest, "branch", "forkroom/{0}".format(exp_id))
    created_at = _string_value(manifest, "created_at", _mtime_text(manifest_path if manifest_exists else exp_path))
    updated_at = _string_value(manifest, "updated_at", _mtime_text(manifest_path if manifest_exists else exp_path))
    summary = _string_value(manifest, "summary", "")
    agent = _string_value(manifest, "agent", "")
    sessions = load_sessions(manifest, warnings, default_agent=agent)

    worktree_path = exp_path / "worktree"
    worktree_exists = worktree_path.exists()
    normalized_worktree_path = worktree_path.resolve(strict=False)
    worktree_registered = normalized_worktree_path in registered_worktrees
    branch_exists = branch in branches

    if not manifest_exists:
        warnings.append("manifest.json is missing")
    if not worktree_exists:
        warnings.append("worktree directory is missing")
    if branch and not branch_exists:
        warnings.append("branch is missing")

    resolved_root = root.resolve(strict=False)
    resolved_worktree = worktree_path.resolve(strict=False)
    link_statuses = [inspect_link(root, worktree_path, resolved_root, resolved_worktree, rule) for rule in links]

    plan_summary, plan_lines = read_plan_summary_and_lines(exp_path / "plan.md")

    outputs_count = count_visible_files(exp_path / "outputs")
    logs_count = count_visible_files(exp_path / "logs")
    runs = load_runs(exp_path, warnings)
    updated_at = latest_timestamp_text([updated_at] + [run.updated_at for run in runs])

    return Experiment(
        key="{0}/{1}".format(project_key, exp_id),
        project_key=project_key,
        project_name=project_name,
        project_root=root,
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
        plan_summary=plan_summary,
        plan_lines=plan_lines,
        outputs_count=outputs_count,
        logs_count=logs_count,
        handoff_exists=(exp_path / "handoff.md").exists(),
        outputs_exists=(exp_path / "outputs").is_dir(),
        logs_exists=(exp_path / "logs").is_dir(),
        runs=runs,
        sessions=sessions,
        warnings=warnings,
        link_statuses=link_statuses,
    )


def load_runs(exp_path: Path, experiment_warnings: List[str]) -> List[Run]:
    runs_path = exp_path / "runs"
    if not runs_path.exists():
        return []
    if not runs_path.is_dir():
        experiment_warnings.append("runs path is not a directory")
        return []

    runs: List[Run] = []
    for run_path in sorted(runs_path.glob("*.json")):
        run = load_run_file(run_path, experiment_warnings)
        if run is not None:
            runs.append(run)
    runs.sort(key=run_updated_sort_key)
    return runs


def run_updated_sort_key(run: Run) -> Tuple[bool, float, str]:
    updated_timestamp = _timestamp_value(run.updated_at)
    return (updated_timestamp is None, -(updated_timestamp or 0), run.id)


def load_run_file(path: Path, experiment_warnings: List[str]) -> Optional[Run]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        experiment_warnings.append("run {0}: JSON is invalid: {1}".format(path.name, exc))
        return None
    if not isinstance(raw, Mapping):
        experiment_warnings.append("run {0}: root must be an object".format(path.name))
        return None

    warnings: List[str] = []
    run_id = _first_string(raw, ("id",)) or path.stem
    if "id" not in raw:
        warnings.append("run {0}: id is missing".format(run_id))
    title = _first_string(raw, ("title", "name")) or run_id
    session_id = _first_string(raw, ("session_id", "session", "thread_id"))
    if not session_id:
        warnings.append("run {0}: session_id is missing".format(run_id))

    status = _first_string(raw, ("status",)) or "unknown"
    completed = parse_run_count(run_id, "completed", raw.get("completed"), warnings)
    total = parse_run_count(run_id, "total", raw.get("total"), warnings)
    message = _first_string(raw, ("message",))
    estimated_end_at = _first_string(raw, ("estimated_end_at", "eta"))
    created_at = _first_string(raw, ("created_at", "started_at"))
    updated_at = _first_string(raw, ("updated_at",)) or _mtime_text(path)
    started_at = _first_string(raw, ("started_at",))
    ended_at = _first_string(raw, ("ended_at",))
    events = raw.get("events", [])
    events_count = len(events) if isinstance(events, list) else 0

    warnings.extend(validate_run_events(run_id, raw))
    experiment_warnings.extend(warnings)
    return Run(
        id=run_id,
        title=title,
        session_id=session_id,
        status=status,
        completed=completed,
        total=total,
        message=message,
        estimated_end_at=estimated_end_at,
        created_at=created_at,
        updated_at=updated_at,
        started_at=started_at,
        ended_at=ended_at,
        path=path,
        events_count=events_count,
        warnings=warnings,
    )


def parse_run_count(run_id: str, label: str, value: Any, warnings: List[str]) -> Optional[int]:
    if value is None:
        return None
    count = validate_count_value(value)
    if count is None:
        warnings.append("run {0}: {1} must be a non-negative integer".format(run_id, label))
    return count


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
    owners: Dict[str, Dict[str, Experiment]] = {}
    for experiment in experiments:
        for session in experiment.sessions:
            owners.setdefault(session.id, {})[experiment.key] = experiment

    duplicate_owners = {
        session_id: owner_map
        for session_id, owner_map in owners.items()
        if len(owner_map) > 1
    }
    if not duplicate_owners:
        return experiments

    use_project_labels = len({experiment.project_key for experiment in experiments}) > 1
    updated: List[Experiment] = []
    for experiment in experiments:
        warnings = list(experiment.warnings)
        for session in experiment.sessions:
            owner_map = duplicate_owners.get(session.id)
            if owner_map:
                other_labels = sorted(
                    experiment_owner_label(owner, use_project_labels)
                    for key, owner in owner_map.items()
                    if key != experiment.key
                )
                warnings.append(
                    "session {0} is also recorded by experiment(s): {1}; a session can only belong to one experiment".format(
                        session.id,
                        ", ".join(other_labels),
                    )
                )
        updated.append(replace(experiment, warnings=warnings))
    return updated


def with_active_run_ownership_warnings(experiments: List[Experiment]) -> List[Experiment]:
    owners: Dict[str, List[Tuple[Experiment, Run]]] = {}
    for experiment in experiments:
        for run in experiment.runs:
            if run.session_id and run.status in ACTIVE_RUN_STATUSES:
                owners.setdefault(run.session_id, []).append((experiment, run))

    duplicate_owners = {
        session_id: owned_runs
        for session_id, owned_runs in owners.items()
        if len(owned_runs) > 1
    }
    if not duplicate_owners:
        return experiments

    use_project_labels = len({experiment.project_key for experiment in experiments}) > 1
    updated: List[Experiment] = []
    for experiment in experiments:
        warnings = list(experiment.warnings)
        for run in experiment.runs:
            owned_runs = duplicate_owners.get(run.session_id)
            if not owned_runs or run.status not in ACTIVE_RUN_STATUSES:
                continue
            other_labels = sorted(
                "{0}/{1}".format(experiment_owner_label(owner, use_project_labels), owned_run.id)
                for owner, owned_run in owned_runs
                if owner.key != experiment.key or owned_run.id != run.id
            )
            warnings.append(
                "session {0} has multiple active runs: {1}; a session can only own one active run".format(
                    run.session_id,
                    ", ".join(other_labels),
                )
            )
        updated.append(replace(experiment, warnings=warnings))
    return updated


def experiment_owner_label(experiment: Experiment, use_project_label: bool) -> str:
    if not use_project_label:
        return experiment.id
    return "{0}/{1}".format(experiment.project_name, experiment.id)


def inspect_link(root: Path, worktree_path: Path, resolved_root: Path, resolved_worktree: Path, rule: LinkRule) -> LinkStatus:
    source_path = root / rule.source
    target_path = worktree_path / rule.target

    source_safe = is_within(source_path.resolve(strict=False), resolved_root)
    target_safe = is_within(target_path.resolve(strict=False), resolved_worktree)
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


def read_plan_summary_and_lines(path: Path) -> Tuple[str, int]:
    if not path.exists():
        return "plan.md is missing", 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return "plan.md could not be read: {0}".format(exc), 0

    lines = [line.strip() for line in text.splitlines()]
    non_empty_lines = [line for line in lines if line]
    if not non_empty_lines:
        return "plan.md is empty", len(lines)
    summary = " ".join(non_empty_lines[:4])
    return summary[:600], len(lines)

def count_visible_files(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    try:
        return len([f for f in path.iterdir() if f.is_file() and not f.name.startswith(".")])
    except Exception:
        return 0


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

    from .time_format import _parse_timestamp
    parsed = _parse_timestamp(text)
    return parsed.timestamp() if parsed else None


def _mtime_text(path: Path) -> str:
    try:
        return str(int(path.stat().st_mtime))
    except OSError:
        return ""


def latest_timestamp_text(values: Sequence[str]) -> str:
    best_text = ""
    best_value: Optional[float] = None
    for value in values:
        timestamp = _timestamp_value(value)
        if timestamp is None:
            if not best_text:
                best_text = value
            continue
        if best_value is None or timestamp > best_value:
            best_value = timestamp
            best_text = value
    return best_text
