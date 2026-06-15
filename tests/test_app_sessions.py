import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import DataTable

from vibe_board.app import VibeBoardApp


class AppSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_focuses_sessions_and_opens_selected_deeplink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exp = root / ".agents" / "exps" / "demo"
            (exp / "worktree").mkdir(parents=True)
            (exp / "outputs").mkdir()
            (exp / "logs").mkdir()
            (exp / "plan.md").write_text("# Plan\n", encoding="utf-8")
            (exp / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "demo",
                        "title": "Demo",
                        "status": "running",
                        "branch": "agents/demo",
                        "sessions": [
                            {
                                "id": "019e7831-63b8-7ca2-a4f7-47593e2846ea",
                                "title": "Demo session",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            app = VibeBoardApp(root=root)
            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                experiments = app.query_one("#experiments", DataTable)
                sessions = app.query_one("#sessions", DataTable)

                self.assertEqual(experiments.row_count, 1)
                self.assertEqual(sessions.row_count, 1)

                await pilot.press("enter")
                await pilot.pause(0.1)
                self.assertIs(app.focused, sessions)

                with patch("vibe_board.app.webbrowser.open", return_value=True) as open_url:
                    await pilot.press("enter")
                    await pilot.pause(0.2)

                open_url.assert_called_once_with("codex://threads/019e7831-63b8-7ca2-a4f7-47593e2846ea")
