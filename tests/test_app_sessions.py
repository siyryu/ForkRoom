import json
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import patch

from rich.padding import Padding
from rich.spinner import Spinner
from textual.widgets import DataTable, Static

from forkroom.app import ForkRoomApp
from forkroom.api import AgentProvider
from forkroom.codex_focus import CodexFocusSummary
from typing import Sequence, Dict, Callable

class FakeAgentProvider(AgentProvider):
    def __init__(self, run_loader: Callable[[Sequence[str]], Dict[str, str]], focus_loader: Callable[[str], CodexFocusSummary]):
        self.run_loader = run_loader
        self.focus_loader = focus_loader
        
    def get_run_states(self, session_ids: Sequence[str], timeout_seconds: float = 4.0) -> Dict[str, str]:
        return self.run_loader(session_ids)
        
    def get_focus(self, session_id: str, timeout_seconds: float = 4.0) -> CodexFocusSummary:
        return self.focus_loader(session_id)

from forkroom.codex_focus import CodexFocusSummary


def column_labels(table: DataTable) -> list[str]:
    return [getattr(column.label, "plain", str(column.label)) for column in table.columns.values()]


def row_values(table: DataTable, row: int) -> list[str]:
    return [str(value) for value in table.get_row_at(row)]


def row_cells(table: DataTable, row: int) -> list[object]:
    return list(table.get_row_at(row))


def make_focus_loader(state: str = "completed"):
    def load_focus(session_id: str) -> CodexFocusSummary:
        return CodexFocusSummary(
            thread_id=session_id,
            state=state,
            focus=(
                "Last command:\n"
                "Summarize visible session activity.\n\n"
                "Codex update:\n"
                "I am summarizing visible session activity."
            ),
            phase="summarizing visible activity",
            last_user_command="Summarize visible session activity.",
            codex_update="I am summarizing visible session activity.",
        )

    return load_focus


def write_experiment(
    root: Path,
    sessions: Optional[list[object]] = None,
    exp_id: str = "demo",
    updated_at: str = "",
) -> None:
    exp = root / ".agents" / "exps" / exp_id
    (exp / "worktree").mkdir(parents=True)
    (exp / "outputs").mkdir()
    (exp / "logs").mkdir()
    (exp / "plan.md").write_text("# Plan\n", encoding="utf-8")
    manifest: dict[str, object] = {
        "id": exp_id,
        "title": exp_id.title(),
        "status": "running",
        "branch": "agents/{0}".format(exp_id),
    }
    if updated_at:
        manifest["updated_at"] = updated_at
    if sessions is not None:
        manifest["sessions"] = sessions
    (exp / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def table_row_keys(table: DataTable) -> list[str]:
    return [str(getattr(row.key, "value", row.key)) for row in table.ordered_rows]


class AppSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_enter_focuses_sessions_and_opens_selected_deeplink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_experiment(
                root,
                sessions=[
                    {
                        "id": "019e7831-63b8-7ca2-a4f7-47593e2846ea",
                        "title": "Demo session",
                    }
                ],
            )

            app = ForkRoomApp(
                root=root,
                agent_provider=FakeAgentProvider(run_loader=lambda ids: {session_id: "completed" for session_id in ids}, focus_loader=make_focus_loader("completed")),
            )
            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                experiments = app.query_one("#experiments", DataTable)
                sessions = app.query_one("#sessions", DataTable)
                links = app.query_one("#links", DataTable)
                details_text = app.query_one("#details").render().plain
                focus_renderable = app.query_one("#codex-focus", Static).render()
                focus_text = focus_renderable.plain
                focus_styles = " ".join(str(span.style) for span in getattr(focus_renderable, "spans", []))

                self.assertEqual(experiments.row_count, 1)
                self.assertEqual(sessions.row_count, 1)
                self.assertEqual(column_labels(experiments), ["", "Title", "Branch", "Updated", "Stats"])
                self.assertEqual(column_labels(sessions), ["ID", "Title", "Run", "Updated"])
                self.assertEqual(row_values(sessions, 0)[2], "completed")
                self.assertEqual(column_labels(links), ["Source", "Target", "Required", "Message", "Description"])
                self.assertEqual(
                    focus_text,
                    "Summarize visible session activity.\n\n"
                    "└─ I am summarizing visible session activity.",
                )
                self.assertIn("bold", focus_styles)
                self.assertNotIn("Codex update:", focus_text)
                self.assertNotIn("Last command:", focus_text)
                self.assertNotIn("State:", focus_text)
                self.assertNotIn("Updated:", focus_text)
                self.assertNotIn("Focus:", focus_text)
                self.assertNotIn("Status:", details_text)
                self.assertNotIn("Git status:", details_text)
                self.assertNotIn("Link status:", details_text)

                await pilot.press("enter")
                await pilot.pause(0.1)
                self.assertIs(app.focused, sessions)
                app.render_experiment_run_indicators()
                self.assertIs(app.focused, sessions)

                with patch("forkroom.app.webbrowser.open", return_value=True) as open_url:
                    await pilot.press("enter")
                    await pilot.pause(0.2)

                open_url.assert_called_once_with("codex://threads/019e7831-63b8-7ca2-a4f7-47593e2846ea")

    async def test_codex_preview_fits_update_to_available_height(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = ForkRoomApp(root=root)
            summary = CodexFocusSummary(
                thread_id="session-1",
                state="active",
                focus="",
                phase="implementing changes",
                last_user_command="Review the preview.",
                codex_update="\n".join("Codex line {0}".format(index) for index in range(1, 8)),
            )

            async with app.run_test():
                focus_text = app.codex_focus_text(summary, height=6, width=80).plain

            self.assertEqual(
                focus_text,
                "Review the preview.\n\n"
                "└─ Codex line 1\n"
                "   Codex line 2\n"
                "   Codex line 3\n"
                "   ...",
            )
            self.assertEqual(len(focus_text.splitlines()), 6)

    async def test_render_selection_keeps_session_rows_when_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_experiment(root, sessions=[{"id": "session-1", "title": "Demo session"}])
            app = ForkRoomApp(
                root=root,
                agent_provider=FakeAgentProvider(run_loader=lambda ids: {"session-1": "active"}, focus_loader=make_focus_loader("active")),
            )

            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                sessions = app.query_one("#sessions", DataTable)

                with patch.object(sessions, "clear", wraps=sessions.clear) as clear:
                    app.render_selection()
                    app.render_selection()

                clear.assert_not_called()
                self.assertEqual(row_values(sessions, 0)[0], "session-1")

    async def test_stale_session_highlight_does_not_change_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_experiment(
                root,
                sessions=[
                    {"id": "session-a", "title": "Session A"},
                    {"id": "session-b", "title": "Session B"},
                ],
            )
            app = ForkRoomApp(
                root=root,
                agent_provider=FakeAgentProvider(run_loader=lambda ids: {session_id: "active" for session_id in ids}, focus_loader=make_focus_loader("active")),
            )

            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                app.selected_session_id = "session-b"
                app.render_selection()
                await pilot.pause(0.1)

                sessions = app.query_one("#sessions", DataTable)
                stale_first_row = sessions.ordered_rows[0]
                self.assertEqual(row_values(sessions, 1)[0], "session-b")

                app.on_data_table_row_highlighted(
                    DataTable.RowHighlighted(sessions, 0, stale_first_row.key)
                )

                self.assertEqual(app.selected_session_id, "session-b")

    async def test_experiment_run_indicator_shows_spinner_for_active_states(self) -> None:
        for run_state in ("active", "waiting"):
            with self.subTest(run_state=run_state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_experiment(root, sessions=[{"id": "session-1", "title": "Demo session"}])
                app = ForkRoomApp(
                    root=root,
                    agent_provider=FakeAgentProvider(run_loader=lambda ids: {session_id: run_state for session_id in ids}, focus_loader=make_focus_loader(run_state)),
                )

                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    experiments = app.query_one("#experiments", DataTable)

                    indicator = row_cells(experiments, 0)[0]
                    self.assertIsInstance(indicator, Padding)
                    self.assertIsInstance(indicator.renderable, Spinner)

    async def test_experiment_run_indicator_is_empty_for_inactive_states(self) -> None:
        for run_state in ("completed", "failed", "error", "unknown"):
            with self.subTest(run_state=run_state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                write_experiment(root, sessions=[{"id": "session-1", "title": "Demo session"}])
                app = ForkRoomApp(
                    root=root,
                    agent_provider=FakeAgentProvider(run_loader=lambda ids: {session_id: run_state for session_id in ids}, focus_loader=make_focus_loader(run_state)),
                )

                async with app.run_test() as pilot:
                    await pilot.pause(0.3)
                    experiments = app.query_one("#experiments", DataTable)

                    self.assertEqual(row_cells(experiments, 0)[0], "")

    async def test_experiment_run_indicator_is_empty_without_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_experiment(root, sessions=None)
            app = ForkRoomApp(
                root=root,
                agent_provider=FakeAgentProvider(run_loader=lambda ids: {session_id: "active" for session_id in ids}, focus_loader=make_focus_loader("active")),
            )

            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                experiments = app.query_one("#experiments", DataTable)
                focus_text = app.query_one("#codex-focus", Static).render().plain

                self.assertEqual(row_cells(experiments, 0)[0], "")
                self.assertEqual(focus_text, "No session selected.")
                self.assertNotIn("└─", focus_text)

    async def test_multi_project_table_shows_project_column_and_correct_details(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_a = Path(tmp) / "alpha"
            root_b = Path(tmp) / "beta"
            write_experiment(root_a, sessions=[{"id": "session-a"}], updated_at="2026-06-15T10:00:00+08:00")
            write_experiment(root_b, sessions=[{"id": "session-b"}], updated_at="2026-06-15T12:00:00+08:00")
            app = ForkRoomApp(
                roots=[root_a, root_b],
                agent_provider=FakeAgentProvider(run_loader=lambda ids: {session_id: "completed" for session_id in ids}, focus_loader=make_focus_loader("completed")),
            )

            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                experiments = app.query_one("#experiments", DataTable)
                details_text = app.query_one("#details").render().plain

                self.assertEqual(column_labels(experiments), ["", "Project", "Title", "Branch", "Updated", "Stats"])
                self.assertEqual(experiments.row_count, 2)
                self.assertEqual(row_values(experiments, 0)[1], "beta")
                self.assertIn("Projects: 2", details_text)
                self.assertIn("Project: beta", details_text)
                self.assertIn("Repository: {0}".format(root_b.resolve()), details_text)

    async def test_multi_project_duplicate_experiment_ids_have_distinct_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_a = Path(tmp) / "alpha"
            root_b = Path(tmp) / "beta"
            write_experiment(root_a, sessions=[{"id": "session-a"}], updated_at="2026-06-15T10:00:00+08:00")
            write_experiment(root_b, sessions=[{"id": "session-b"}], updated_at="2026-06-15T11:00:00+08:00")
            app = ForkRoomApp(
                roots=[root_a, root_b],
                agent_provider=FakeAgentProvider(run_loader=lambda ids: {session_id: "active" for session_id in ids}, focus_loader=make_focus_loader("active")),
            )

            async with app.run_test() as pilot:
                await pilot.pause(0.3)
                experiments = app.query_one("#experiments", DataTable)

                keys = table_row_keys(experiments)
                self.assertEqual(len(keys), 2)
                self.assertEqual(len(set(keys)), 2)
                self.assertEqual([row_values(experiments, row)[2] for row in range(2)], ["Demo", "Demo"])

    async def test_multi_project_session_run_loader_receives_deduped_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root_a = Path(tmp) / "alpha"
            root_b = Path(tmp) / "beta"
            write_experiment(root_a, sessions=[{"id": "shared-session"}], updated_at="2026-06-15T10:00:00+08:00")
            write_experiment(root_b, sessions=[{"id": "shared-session"}], updated_at="2026-06-15T11:00:00+08:00")
            loaded_ids: list[tuple[str, ...]] = []

            def load_runs(ids):
                loaded_ids.append(tuple(ids))
                return {session_id: "completed" for session_id in ids}

            app = ForkRoomApp(
                roots=[root_a, root_b],
                agent_provider=FakeAgentProvider(run_loader=load_runs, focus_loader=make_focus_loader("completed")),
            )

            async with app.run_test() as pilot:
                await pilot.pause(0.3)

            self.assertIn(("shared-session",), loaded_ids)
