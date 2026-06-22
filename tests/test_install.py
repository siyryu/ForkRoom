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

    result = install.install_forkroom(
        root=root,
        source=str(source),
        link_skills=False,
        install_tool=False,
    )

    assert result.tool_installed is False
    assert sorted(result.installed_entries) == ["forkroom", "forkroom-init.md", "forkroom-run.md"]
    assert (skills_dir / "custom.md").read_text(encoding="utf-8") == "keep me\n"
    assert (skills_dir / "forkroom-init.md").read_text(encoding="utf-8") == "new init\n"
    assert (skills_dir / "forkroom" / "SKILL.md").read_text(encoding="utf-8") == "new skill\n"


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
    assert (skills_dir / "forkroom-init.md").is_symlink()
    assert (skills_dir / "forkroom-init.md").resolve() == (source / "skills" / "forkroom-init.md").resolve()
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
    (skills / "forkroom").mkdir(parents=True)
    (skills / "forkroom-init.md").write_text("new init\n", encoding="utf-8")
    (skills / "forkroom-run.md").write_text("new run\n", encoding="utf-8")
    (skills / "forkroom" / "SKILL.md").write_text("new skill\n", encoding="utf-8")
    return source
