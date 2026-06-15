import asyncio
import time
import webbrowser
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Sequence

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static

from .codex_status import UNKNOWN_RUN_STATE, load_codex_run_states
from .models import AgentSession, Experiment, Snapshot
from .scanner import scan_repository

SessionRunLoader = Callable[[Sequence[str]], Mapping[str, str]]


class VibeBoardApp(App):
    """Read-only dashboard for worktree-backed experiments."""

    AUTO_REFRESH_SECONDS = 2.0
    CODEX_RUN_REFRESH_SECONDS = 10.0

    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
    }

    #experiments-panel {
        width: 100%;
        height: 1fr;
        border: solid $accent;
    }

    #lower-panels {
        width: 100%;
        height: 1fr;
    }

    #details-panel {
        width: 2fr;
        height: 100%;
    }

    #details {
        width: 100%;
        height: 1fr;
        border: solid $accent;
        padding: 1 2;
        overflow-y: auto;
    }

    #sessions-panel {
        width: 3fr;
        height: 100%;
        border: solid $accent;
    }

    #links {
        width: 100%;
        height: 8;
        border: solid $accent;
    }

    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("escape", "focus_experiments", "Experiments"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, root: Path, session_run_loader: Optional[SessionRunLoader] = None) -> None:
        super().__init__()
        self.root = root
        self.session_run_loader = session_run_loader or load_codex_run_states
        self.snapshot: Optional[Snapshot] = None
        self.selected_exp_id: Optional[str] = None
        self.selected_session_id: Optional[str] = None
        self.session_run_states: Dict[str, str] = {}
        self.session_run_ids: Sequence[str] = ()
        self.last_session_run_refresh = 0.0
        self.refresh_worker = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
            with Vertical(id="experiments-panel"):
                yield Static("Experiments", id="experiments-title")
                yield DataTable(id="experiments", cursor_type="row")
            with Horizontal(id="lower-panels"):
                with Vertical(id="details-panel"):
                    yield Static("Loading repository state...", id="details")
                    yield DataTable(id="links")
                with Vertical(id="sessions-panel"):
                    yield Static("Sessions (0)", id="sessions-title")
                    yield DataTable(id="sessions", cursor_type="row")
        yield Footer()

    def on_mount(self) -> None:
        experiments = self.query_one("#experiments", DataTable)
        experiments.add_columns("ID", "Title", "Branch", "Updated")
        sessions = self.query_one("#sessions", DataTable)
        sessions.add_columns("ID", "Title", "Run", "Updated")
        links = self.query_one("#links", DataTable)
        links.add_columns("Source", "Target", "Required", "Message", "Description")
        self.set_interval(self.AUTO_REFRESH_SECONDS, self.action_refresh, name="auto-refresh")
        self.action_refresh()
        experiments.focus()

    def action_refresh(self) -> None:
        if self.refresh_worker is not None and not self.refresh_worker.is_finished:
            return
        self.refresh_worker = self.run_worker(self.refresh_snapshot(), name="refresh", group="scan", exclusive=True)

    async def refresh_snapshot(self) -> None:
        snapshot = await asyncio.to_thread(scan_repository, self.root)
        self.snapshot = snapshot
        if self.selected_exp_id not in {experiment.id for experiment in snapshot.experiments}:
            self.selected_exp_id = snapshot.experiments[0].id if snapshot.experiments else None
        self.render_snapshot()
        await self.refresh_session_run_states(snapshot)
        self.render_selection()

    async def refresh_session_run_states(self, snapshot: Snapshot) -> None:
        session_ids = tuple(sorted({session.id for experiment in snapshot.experiments for session in experiment.sessions}))
        if not session_ids:
            self.session_run_states = {}
            self.session_run_ids = ()
            return
        if not self.should_refresh_session_run_states(session_ids):
            return

        try:
            loaded_states = await asyncio.to_thread(self.session_run_loader, session_ids)
        except Exception:
            loaded_states = {}
        self.session_run_states = {
            session_id: loaded_states.get(session_id, UNKNOWN_RUN_STATE) for session_id in session_ids
        }
        self.session_run_ids = session_ids
        self.last_session_run_refresh = time.monotonic()

    def should_refresh_session_run_states(self, session_ids: Sequence[str]) -> bool:
        if tuple(session_ids) != tuple(self.session_run_ids):
            return True
        return time.monotonic() - self.last_session_run_refresh >= self.CODEX_RUN_REFRESH_SECONDS

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row_key = row_key_value(event.row_key)
        if event.data_table.id == "experiments":
            if row_key != self.selected_exp_id:
                self.selected_exp_id = row_key
                self.selected_session_id = None
                self.render_selection()
            return
        if event.data_table.id == "sessions":
            self.selected_session_id = row_key

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = row_key_value(event.row_key)
        if event.data_table.id == "experiments":
            self.selected_exp_id = row_key
            self.render_selection()
            self.focus_sessions()
            return
        if event.data_table.id == "sessions":
            self.selected_session_id = row_key
            session = self.selected_session()
            if session is None:
                self.notify("No session selected.", severity="warning")
                return
            self.run_worker(self.open_session_deeplink(session), name="open-session", group="open", exclusive=True)

    def render_snapshot(self) -> None:
        if self.snapshot is None:
            return

        table = self.query_one("#experiments", DataTable)
        table.clear()
        selected_row = 0
        for index, experiment in enumerate(self.snapshot.experiments):
            table.add_row(
                experiment.id,
                experiment.title,
                experiment.branch,
                experiment.updated_at,
                key=experiment.id,
            )
            if experiment.id == self.selected_exp_id:
                selected_row = index
        if self.snapshot.experiments:
            table.move_cursor(row=selected_row, column=0, animate=False)
        self.render_selection()

    def render_selection(self) -> None:
        if self.snapshot is None:
            return

        experiment = self.selected_experiment()
        self.query_one("#details", Static).update(self.details_text(experiment))
        self.render_sessions(experiment)
        self.render_links(experiment)

    def render_sessions(self, experiment: Optional[Experiment]) -> None:
        sessions = self.query_one("#sessions", DataTable)
        title = self.query_one("#sessions-title", Static)
        sessions.clear()

        if experiment is None:
            self.selected_session_id = None
            title.update("Sessions (0)")
            return

        title.update("Sessions ({0})".format(len(experiment.sessions)))
        session_ids = {session.id for session in experiment.sessions}
        if self.selected_session_id not in session_ids:
            self.selected_session_id = experiment.sessions[0].id if experiment.sessions else None

        selected_row = 0
        for index, session in enumerate(experiment.sessions):
            sessions.add_row(
                session.id,
                session.title,
                self.session_run_state(session),
                session.updated_at or session.created_at or "unknown",
                key=session.id,
            )
            if session.id == self.selected_session_id:
                selected_row = index
        if experiment.sessions:
            sessions.move_cursor(row=selected_row, column=0, animate=False)

    def render_links(self, experiment: Optional[Experiment]) -> None:
        links = self.query_one("#links", DataTable)
        links.clear()

        if experiment is None:
            rules = self.snapshot.map_config.links if self.snapshot else []
            for rule in rules:
                links.add_row(rule.source, rule.target, str(rule.required), "", rule.description)
            return

        for link in experiment.link_statuses:
            links.add_row(
                link.rule.source,
                link.rule.target,
                str(link.rule.required),
                link.message,
                link.rule.description,
            )

    def selected_experiment(self) -> Optional[Experiment]:
        if self.snapshot is None or self.selected_exp_id is None:
            return None
        for experiment in self.snapshot.experiments:
            if experiment.id == self.selected_exp_id:
                return experiment
        return None

    def selected_session(self) -> Optional[AgentSession]:
        experiment = self.selected_experiment()
        if experiment is None or self.selected_session_id is None:
            return None
        for session in experiment.sessions:
            if session.id == self.selected_session_id:
                return session
        return None

    def session_run_state(self, session: AgentSession) -> str:
        return self.session_run_states.get(session.id, UNKNOWN_RUN_STATE)

    def focus_sessions(self) -> None:
        experiment = self.selected_experiment()
        if experiment is None:
            self.notify("No experiment selected.", severity="warning")
            return
        if not experiment.sessions:
            self.notify("No sessions recorded for {0}.".format(experiment.id), severity="warning")
            return
        self.query_one("#sessions", DataTable).focus()

    def action_focus_experiments(self) -> None:
        self.query_one("#experiments", DataTable).focus()

    async def open_session_deeplink(self, session: AgentSession) -> None:
        try:
            opened = await asyncio.to_thread(webbrowser.open, session.deeplink)
        except Exception as exc:
            self.notify("Failed to open session: {0}".format(exc), severity="error")
            return
        if opened:
            self.notify("Opening session {0}".format(session.id), severity="information")
        else:
            self.notify("Could not open {0}".format(session.deeplink), severity="error")

    def details_text(self, experiment: Optional[Experiment]) -> str:
        snapshot = self.snapshot
        if snapshot is None:
            return "Loading repository state..."

        lines = [
            "Repository: {0}".format(snapshot.root),
            "Experiments: {0}".format(snapshot.exps_path),
            "Map config: {0}".format(snapshot.map_config.path),
        ]
        if snapshot.git_error:
            lines.append("Git error: {0}".format(snapshot.git_error))
        if snapshot.map_config.error:
            lines.append("Map config error: {0}".format(snapshot.map_config.error))
        if not snapshot.map_config.exists:
            lines.append("Map config: missing")
        else:
            lines.append("Map links: {0}".format(len(snapshot.map_config.links)))

        if experiment is None:
            lines.extend(["", "No experiment selected."])
            if not snapshot.experiments:
                lines.append("No experiments found under .agents/exps.")
            return "\n".join(lines)

        lines.extend(
            [
                "",
                "Experiment: {0}".format(experiment.id),
                "Title: {0}".format(experiment.title),
                "Branch: {0} ({1})".format(experiment.branch, "exists" if experiment.branch_exists else "missing"),
                "Agent: {0}".format(experiment.agent or "unknown"),
                "Created: {0}".format(experiment.created_at or "unknown"),
                "Updated: {0}".format(experiment.updated_at or "unknown"),
                "Path: {0}".format(experiment.path),
                "Worktree: {0} ({1})".format(
                    experiment.worktree_path,
                    "registered" if experiment.worktree_registered else "not registered",
                ),
                "Worktree exists: {0}".format(experiment.worktree_exists),
                "Sessions: {0}".format(len(experiment.sessions)),
                "Handoff: {0}".format("present" if experiment.handoff_exists else "missing"),
                "Outputs dir: {0}".format("present" if experiment.outputs_exists else "missing"),
                "Logs dir: {0}".format("present" if experiment.logs_exists else "missing"),
            ]
        )
        if experiment.summary:
            lines.extend(["", "Summary:", experiment.summary])
        lines.extend(["", "Plan:", experiment.plan_summary])
        if experiment.warnings:
            lines.extend(["", "Warnings:"])
            lines.extend("- {0}".format(warning) for warning in experiment.warnings)
        return "\n".join(lines)


def row_key_value(row_key: object) -> str:
    return str(getattr(row_key, "value", row_key))
