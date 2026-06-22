from pathlib import Path


def test_run_skill_templates_exist_and_require_eta() -> None:
    templates = Path("skills/forkroom-run/templates")

    for name in ("shell.md", "python.md", "node.md"):
        text = (templates / name).read_text(encoding="utf-8")
        assert "estimated_end_at" in text
        assert "completed" in text
        assert "total" in text
        assert "terminal run cannot be updated" in text
        assert "template-update" in text


def test_run_skill_explains_session_uniqueness() -> None:
    text = Path("skills/forkroom-run.md").read_text(encoding="utf-8")

    assert "only one active run" in text
    assert "must not create runs" in text
    assert "forkroom run start" in text
