import json
import tempfile
import unittest
from pathlib import Path

from vibe_board.scanner import codex_thread_deeplink, load_experiments, load_sessions


class ScannerSessionTests(unittest.TestCase):
    def test_load_sessions_supports_objects_and_default_deeplinks(self) -> None:
        warnings = []
        sessions = load_sessions(
            {
                "sessions": [
                    {
                        "thread_id": "019e7831-63b8-7ca2-a4f7-47593e2846ea",
                        "title": "Implement sessions",
                        "status": "running",
                    },
                    "plain-session-id",
                ],
                "agent": "codex",
            },
            warnings,
            default_agent="codex",
        )

        self.assertEqual(warnings, [])
        self.assertEqual([session.id for session in sessions], ["019e7831-63b8-7ca2-a4f7-47593e2846ea", "plain-session-id"])
        self.assertEqual(sessions[0].title, "Implement sessions")
        self.assertEqual(sessions[0].agent, "codex")
        self.assertEqual(sessions[0].deeplink, "codex://threads/019e7831-63b8-7ca2-a4f7-47593e2846ea")
        self.assertEqual(sessions[1].deeplink, "codex://threads/plain-session-id")

    def test_codex_thread_deeplink_escapes_session_ids(self) -> None:
        self.assertEqual(codex_thread_deeplink("thread with spaces"), "codex://threads/thread%20with%20spaces")

    def test_duplicate_session_ownership_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            one = root / ".agents" / "exps" / "one"
            two = root / ".agents" / "exps" / "two"
            for exp_path in (one, two):
                (exp_path / "worktree").mkdir(parents=True)
                (exp_path / "outputs").mkdir()
                (exp_path / "logs").mkdir()
                (exp_path / "plan.md").write_text("# Plan\n", encoding="utf-8")
            (one / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "one",
                        "title": "One",
                        "branch": "agents/one",
                        "sessions": [{"id": "shared-session"}],
                    }
                ),
                encoding="utf-8",
            )
            (two / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "two",
                        "title": "Two",
                        "branch": "agents/two",
                        "sessions": [{"id": "shared-session"}],
                    }
                ),
                encoding="utf-8",
            )

            experiments = load_experiments(
                root,
                links=[],
                registered_worktrees={(one / "worktree").resolve(), (two / "worktree").resolve()},
                branches={"agents/one", "agents/two"},
            )

        warnings = {experiment.id: "\n".join(experiment.warnings) for experiment in experiments}
        self.assertIn("session shared-session is also recorded by experiment(s): two", warnings["one"])
        self.assertIn("session shared-session is also recorded by experiment(s): one", warnings["two"])


if __name__ == "__main__":
    unittest.main()
