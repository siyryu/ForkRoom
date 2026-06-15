import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import DataTable

from vibe_board.app import VibeBoardApp


def column_labels(table: DataTable) -> list[str]:
    return [getattr(column.label, "plain", str(column.label)) for column in table.columns.values()]


def row_values(table: DataTable, row: int) -> list[str]:
    return [str(value) for value in table.get_row_at(row)]


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

            app = VibeBoardApp(root=root, session_run_loader=lambda ids: {session_id: "completed" for session_id in ids})
            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                experiments = app.query_one("#experiments", DataTable)
                sessions = app.query_one("#sessions", DataTable)
                links = app.query_one("#links", DataTable)
                details_text = app.query_one("#details").render().plain

                self.assertEqual(experiments.row_count, 1)
                self.assertEqual(sessions.row_count, 1)
                self.assertEqual(column_labels(experiments), ["ID", "Title", "Branch", "Updated"])
                self.assertEqual(column_labels(sessions), ["ID", "Title", "Run", "Updated"])
                self.assertEqual(row_values(sessions, 0)[2], "completed")
                self.assertEqual(column_labels(links), ["Source", "Target", "Required", "Message", "Description"])
                self.assertNotIn("Status:", details_text)
                self.assertNotIn("Git status:", details_text)
                self.assertNotIn("Link status:", details_text)

                await pilot.press("enter")
                await pilot.pause(0.1)
                self.assertIs(app.focused, sessions)

                with patch("vibe_board.app.webbrowser.open", return_value=True) as open_url:
                    await pilot.press("enter")
                    await pilot.pause(0.2)

                open_url.assert_called_once_with("codex://threads/019e7831-63b8-7ca2-a4f7-47593e2846ea")
