from pathlib import Path


def test_install_section_stays_minimal() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    install_section = section(readme, "## Install", "## Usage")

    assert "uvx --from git+https://github.com/siyryu/forkroom.git forkroom install" in install_section
    assert install_section.count("```bash") == 1
    assert "uv tool install --force --editable" not in install_section
    assert "CODEX_SKILLS_DIR" not in install_section
    assert "git clone" not in install_section


def test_contribute_section_keeps_developer_install_flow() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert readme.index("## Usage") < readme.index("## Contribute")
    contribute_section = readme[readme.index("## Contribute") :]

    assert "uv tool install --force --editable ." in contribute_section
    assert "forkroom install --root /path/to/your-project --source . --link-skills --no-tool-install" in contribute_section
    assert "uv run --with pytest python -m pytest" in contribute_section


def section(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]
