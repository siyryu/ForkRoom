import json
import subprocess
from pathlib import Path
import pytest

def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return init_repo(tmp_path)

def init_repo(
    tmp_path: Path,
    *,
    files: dict[str, str] | None = None,
    map_config: dict | None = None,
) -> Path:
    root = tmp_path / "repo"
    if not root.exists():
        root.mkdir(parents=True, exist_ok=True)
        git(root, "init")
        git(root, "checkout", "-b", "main")
        git(root, "config", "user.name", "Test User")
        git(root, "config", "user.email", "test@example.com")

        (root / ".gitignore").write_text(".agents/\n", encoding="utf-8")
        (root / "README.md").write_text("# Test Repo\n", encoding="utf-8")
        
    for name, content in (files or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    if map_config is not None:
        agents_dir = root / ".vibe-board"
        agents_dir.mkdir(parents=True, exist_ok=True)
        (agents_dir / "worktree-map.json").write_text(json.dumps(map_config), encoding="utf-8")

    git(root, "add", ".")
    git(root, "commit", "-m", "Initial commit")
    return root
