import json
import tempfile
import unittest
from pathlib import Path
from typing import Dict, Sequence

from rich.padding import Padding
from rich.spinner import Spinner
from textual.widgets import DataTable, Static

from vibe_board.api import AgentProvider
from vibe_board.app import VibeBoardApp
from vibe_board.codex_focus import CodexFocusSummary


class FakeAgentProvider(AgentProvider):
    def get_run_states(self, session_ids: Sequence[str], timeout_seconds: float = 4.0) -> Dict[str, str]:
        return {}

    def get_focus(self, session_id: str, timeout_seconds: float = 4.0) -> CodexFocusSummary:
        return CodexFocusSummary(thread_id=session_id, state="completed", focus="")


def row_cells(table: DataTable, row: int) -> list[object]:
    return list(table.get_row_at(row))


class AppRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_active_tracked_run_shows_spinner_stats_and_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_experiment_with_run(root)
            app = VibeBoardApp(root=root, agent_provider=FakeAgentProvider())

            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                experiments = app.query_one("#experiments", DataTable)
                details = app.query_one("#details", Static).render().plain

                indicator = row_cells(experiments, 0)[0]
                stats = row_cells(experiments, 0)[4]

                self.assertIsInstance(indicator, Padding)
                self.assertIsInstance(indicator.renderable, Spinner)
                stats_text = str(stats)
                self.assertIn("Run: 42/100 ETA", stats_text)
                self.assertLess(stats_text.index("Outs: 1"), stats_text.index("Run: 42/100"))
                self.assertIn("Runs: 1", details)
                self.assertIn("Active runs: 1", details)
                self.assertIn("Progress: 42/100", details)
                self.assertIn("ETA:", details)


def write_experiment_with_run(root: Path) -> None:
    exp = root / ".agents" / "exps" / "demo"
    (exp / "worktree").mkdir(parents=True)
    (exp / "outputs").mkdir()
    (exp / "logs").mkdir()
    (exp / "outputs" / "artifact.txt").write_text("artifact\n", encoding="utf-8")
    (exp / "manifest.json").write_text(
        json.dumps(
            {
                "id": "demo",
                "title": "Demo",
                "status": "running",
                "branch": "agents/demo",
                "updated_at": "2026-06-15T10:00:00+08:00",
            }
        ),
        encoding="utf-8",
    )
    runs = exp / "runs"
    runs.mkdir()
    (runs / "crawl-pages.json").write_text(
        json.dumps(
            {
                "id": "crawl-pages",
                "title": "Crawl pages",
                "session_id": "session-1",
                "status": "running",
                "completed": 42,
                "total": 100,
                "message": "Crawling",
                "estimated_end_at": "2026-06-15T12:00:00+08:00",
                "created_at": "2026-06-15T10:00:00+08:00",
                "updated_at": "2026-06-15T10:30:00+08:00",
                "started_at": "2026-06-15T10:00:00+08:00",
                "ended_at": "",
                "events": [
                    {
                        "type": "start",
                        "status": "running",
                        "completed": 42,
                        "total": 100,
                        "message": "Crawling",
                        "estimated_end_at": "2026-06-15T12:00:00+08:00",
                        "updated_at": "2026-06-15T10:30:00+08:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
