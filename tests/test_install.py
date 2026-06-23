import subprocess
from pathlib import Path

from forkroom import install


def test_install_copies_forkroom_skills_without_touching_other_skills(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    skills_dir = root / ".codex" / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "custom.md").write_text("keep me\n", encoding="utf-8")
    (skills_dir / "forkroom-init.md").write_text("old\n", encoding="utf-8")
    (skills_dir / "forkroom-run").mkdir()

    result = install.install_forkroom(
        root=root,
        source=str(source),
        link_skills=False,
        install_tool=False,
    )

    assert result.tool_installed is False
    assert sorted(result.installed_entries) == ["forkroom"]
    assert (skills_dir / "custom.md").read_text(encoding="utf-8") == "keep me\n"
    assert not (skills_dir / "forkroom-init.md").exists()
    assert not (skills_dir / "forkroom-run").exists()
    assert (skills_dir / "forkroom" / "SKILL.md").read_text(encoding="utf-8") == "new skill\n"
    assert (skills_dir / "forkroom" / "references" / "init.md").read_text(encoding="utf-8") == "new init\n"


def test_install_links_skills_from_local_source(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    root = tmp_path / "project"
    root.mkdir()

    install.install_forkroom(
        root=root,
        source=str(source),
        link_skills=True,
        install_tool=False,
    )

    skills_dir = root / ".codex" / "skills"
    assert (skills_dir / "forkroom").is_symlink()
    assert (skills_dir / "forkroom").resolve() == (source / "skills" / "forkroom").resolve()


def test_install_skips_tool_install_when_requested(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    calls = []

    def runner(command, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    result = install.install_forkroom(
        root=root,
        source=str(source),
        link_skills=False,
        install_tool=False,
        runner=runner,
    )

    assert result.tool_installed is False
    assert calls == []


def test_install_runs_uv_tool_install_by_default(tmp_path: Path) -> None:
    source = make_source(tmp_path)
    root = tmp_path / "project"
    root.mkdir()
    calls = []

    def runner(command, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0)

    result = install.install_forkroom(
        root=root,
        source=str(source),
        link_skills=False,
        install_tool=True,
        runner=runner,
    )

    assert result.tool_installed is True
    assert calls == [["uv", "tool", "install", "--force", str(source)]]


def make_source(tmp_path: Path) -> Path:
    source = tmp_path / "forkroom-source"
    skills = source / "skills"
    (skills / "forkroom" / "references").mkdir(parents=True)
    (skills / "forkroom" / "SKILL.md").write_text("new skill\n", encoding="utf-8")
    (skills / "forkroom" / "references" / "init.md").write_text("new init\n", encoding="utf-8")
    (skills / "forkroom" / "references" / "run.md").write_text("new run\n", encoding="utf-8")
    return source
