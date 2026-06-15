from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass(frozen=True)
class AgentSession:
    id: str
    title: str
    agent: str
    status: str
    created_at: str
    updated_at: str
    deeplink: str
    origin: str = ""


@dataclass(frozen=True)
class LinkRule:
    source: str
    target: str
    required: bool
    description: str = ""


@dataclass(frozen=True)
class LinkStatus:
    rule: LinkRule
    status: str
    message: str
    source_exists: bool
    target_exists: bool
    target_is_symlink: bool
    points_to_expected: bool


@dataclass(frozen=True)
class MapConfig:
    path: Path
    exists: bool
    version: Optional[int]
    links: List[LinkRule] = field(default_factory=list)
    error: Optional[str] = None


@dataclass(frozen=True)
class Experiment:
    id: str
    title: str
    status: str
    branch: str
    created_at: str
    updated_at: str
    summary: str
    agent: str
    path: Path
    worktree_path: Path
    worktree_exists: bool
    worktree_registered: bool
    branch_exists: bool
    plan_summary: str
    handoff_exists: bool
    outputs_exists: bool
    logs_exists: bool
    git_status: str
    sessions: List[AgentSession] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    link_statuses: List[LinkStatus] = field(default_factory=list)


@dataclass(frozen=True)
class Snapshot:
    root: Path
    exps_path: Path
    map_config: MapConfig
    experiments: List[Experiment]
    git_error: Optional[str] = None
