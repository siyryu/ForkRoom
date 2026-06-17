import asyncio
import re
import time
import subprocess
from datetime import datetime
import webbrowser
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from rich.padding import Padding
from rich.spinner import Spinner
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static

from .codex_focus import CodexFocusSummary, load_codex_focus, unavailable_focus
from .codex_status import UNKNOWN_RUN_STATE, load_codex_run_states
from .models import AgentSession, Experiment, ProjectSnapshot, Snapshot
from .scanner import normalize_roots, scan_repositories
from .time_format import friendly_time

SessionRunLoader = Callable[[Sequence[str]], Mapping[str, str]]
SessionFocusLoader = Callable[[str], CodexFocusSummary]


class VibeBoardApp(App):
    """Read-only dashboard for worktree-backed experiments."""

    AUTO_REFRESH_SECONDS = 2.0
    CODEX_RUN_REFRESH_SECONDS = 10.0
    CODEX_FOCUS_ACTIVE_REFRESH_SECONDS = 2.0
    CODEX_FOCUS_IDLE_REFRESH_SECONDS = 10.0
    ACTIVE_EXPERIMENT_RUN_STATES = {"active", "waiting"}

    CSS = """
    Screen {
        layout: vertical;
    }

    Header, Footer, Footer > .footer--key, DataTable > .datatable--header {
        background: $background;
        color: $foreground;
    }

    HeaderIcon, HeaderTitle, HeaderClock {
        background: $background;
        color: $foreground;
    }

    DataTable > .datatable--cursor {
        background: $foreground;
        color: $background;
    }

    #body {
        height: 1fr;
    }

    #experiments-panel {
        width: 100%;
        height: 1fr;
        padding: 0 1;
    }

    #experiments-title {
        padding: 1 0 1 1;
    }

    #lower-panels {
        width: 100%;
        height: 1fr;
    }

    #details-panel {
        width: 2fr;
        height: 100%;
        display: none;
    }

    #details {
        width: 100%;
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }

    #sessions-panel {
        width: 3fr;
        height: 100%;
        padding: 0 1;
    }

    #sessions-title {
        padding: 1 0 1 1;
    }

    #links {
        width: 100%;
        height: 8;
    }

    #sessions {
        height: 1fr;
    }

    #codex-focus {
        height: 2fr;
        background: $surface;
        padding: 1 2;
        margin-top: 1;
        overflow-y: auto;
    }

    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("i", "toggle_info", "Toggle Info"),
        ("escape", "focus_experiments", "Experiments"),
        ("o", "open_experiment", "Open in Zed"),
        ("c", "copy_info", "Copy Info"),
        Binding("j", "vim_down", "Down", show=False),
        Binding("k", "vim_up", "Up", show=False),
        ("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        root: Optional[Path] = None,
        roots: Optional[Sequence[Path]] = None,
        session_run_loader: Optional[SessionRunLoader] = None,
        session_focus_loader: Optional[SessionFocusLoader] = None,
    ) -> None:
        super().__init__()
        self.roots = tuple(normalize_roots(roots or ([root] if root is not None else [Path(".")])))
        self.root = self.roots[0]
        self.show_project_column = len(self.roots) > 1
        self.session_run_loader = session_run_loader or load_codex_run_states
        self.session_focus_loader = session_focus_loader or load_codex_focus
        self.snapshot: Optional[Snapshot] = None
        self.selected_exp_key: Optional[str] = None
        self.selected_session_id: Optional[str] = None
        self.session_run_states: Dict[str, str] = {}
        self.session_run_ids: Sequence[str] = ()
        self.session_focus_worker = None
        self.session_focus_worker_id: Optional[str] = None
        self._experiment_has_active_run_cache: Dict[str, bool] = {}
        self.experiment_run_spinners: Dict[str, Spinner] = {}
        self.worktree_stats: Dict[str, str] = {}
        self.last_session_run_refresh = 0.0
        self.refresh_worker = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, classes="custom-header")
        with Vertical(id="body"):
            with Vertical(id="experiments-panel"):
                yield Static("EXPERIMENTS", id="experiments-title")
                yield DataTable(id="experiments", cursor_type="row")
            with Horizontal(id="lower-panels"):
                with Vertical(id="details-panel"):
                    yield Static("Scanning worktrees and experiments...", id="details")
                    yield DataTable(id="links")
                with Vertical(id="sessions-panel"):
                    yield Static("SESSIONS (0)", id="sessions-title")
                    yield DataTable(id="sessions", cursor_type="row")
                    yield Static(self.codex_focus_placeholder(), id="codex-focus")
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "textual-dark"
        experiments = self.query_one("#experiments", DataTable)
        experiments.add_column("", width=4, key="run")
        if self.show_project_column:
            experiments.add_column("Project", key="project")
        experiments.add_column("Title", key="title")
        experiments.add_column("Branch", key="branch")
        experiments.add_column("Updated", key="updated")
        experiments.add_column("Stats", key="stats")
        sessions = self.query_one("#sessions", DataTable)
        sessions.add_columns(("ID", "id"), ("Title", "title"), ("Run", "run"), ("Updated", "updated"))
        links = self.query_one("#links", DataTable)
        links.add_columns("Source", "Target", "Required", "Message", "Description")
        self.set_interval(self.AUTO_REFRESH_SECONDS, self.action_refresh, name="auto-refresh")
        self.set_interval(0.25, self.render_experiment_run_indicators, name="run-indicator-animation")
        self.action_refresh()
        experiments.focus()

    def action_toggle_info(self) -> None:
        panel = self.query_one("#details-panel")
        panel.display = not panel.display

    def action_open_experiment(self) -> None:
        experiment = self.selected_experiment()
        if experiment is None:
            self.notify("No experiment selected.", severity="warning")
            return
        self.run_worker(self._open_in_zed(experiment.path), name="open-zed", group="open", exclusive=True)

    async def _open_in_zed(self, path: Path) -> None:
        try:
            if not path.exists():
                self.notify("Experiment path does not exist.", severity="error")
                return
            process = await asyncio.create_subprocess_exec("zed", str(path))
            await process.wait()
            self.notify(f"Opened {path.name} in Zed.", severity="information")
        except Exception as exc:
            self.notify(f"Failed to open in Zed: {exc}", severity="error")

    def action_copy_info(self) -> None:
        experiment = self.selected_experiment()
        if experiment is None:
            self.notify("No experiment selected.", severity="warning")
            return

        info = (
            f"Experiment: {experiment.id}\n"
            f"Branch: {experiment.branch}\n"
            f"Worktree: {experiment.worktree_path.resolve()}\n"
            f"Command: cd {experiment.worktree_path.resolve()}"
        )
        self.app.copy_to_clipboard(info)
        self.notify(f"Copied info for {experiment.id}", severity="information")

    def action_refresh(self) -> None:
        if self.refresh_worker is not None and not self.refresh_worker.is_finished:
            return
        self.refresh_worker = self.run_worker(self.refresh_snapshot(), name="refresh", group="scan", exclusive=True)

    def action_vim_down(self) -> None:
        focused = self.focused
        if hasattr(focused, "action_cursor_down"):
            focused.action_cursor_down()
        elif hasattr(focused, "action_scroll_down"):
            focused.action_scroll_down()

    def action_vim_up(self) -> None:
        focused = self.focused
        if hasattr(focused, "action_cursor_up"):
            focused.action_cursor_up()
        elif hasattr(focused, "action_scroll_up"):
            focused.action_scroll_up()

    async def refresh_snapshot(self) -> None:
        snapshot = await asyncio.to_thread(scan_repositories, self.roots)
        self.snapshot = snapshot
        if self.selected_exp_key not in {experiment.key for experiment in snapshot.experiments}:
            self.selected_exp_key = snapshot.experiments[0].key if snapshot.experiments else None
        self.render_snapshot()
        await asyncio.gather(
            self.refresh_session_run_states(snapshot),
            self.refresh_worktree_stats(snapshot)
        )
        self.render_selection()

    async def refresh_session_run_states(self, snapshot: Snapshot) -> None:
        session_ids = tuple(sorted({session.id for experiment in snapshot.experiments for session in experiment.sessions}))
        if not session_ids:
            self.session_run_states = {}
            self.session_run_ids = ()
            self.render_experiment_run_indicators()
            return
        if not self.should_refresh_session_run_states(session_ids):
            self.render_experiment_run_indicators()
            return

        try:
            loaded_states = await asyncio.to_thread(self.session_run_loader, session_ids)
        except Exception:
            loaded_states = {}
        self.session_run_states = {
            session_id: loaded_states.get(session_id, UNKNOWN_RUN_STATE) for session_id in session_ids
        }
        self.session_run_ids = session_ids
        self._experiment_has_active_run_cache.clear()
        self.last_session_run_refresh = time.monotonic()
        self.render_experiment_run_indicators()

    def should_refresh_session_run_states(self, session_ids: Sequence[str]) -> bool:
        if tuple(session_ids) != tuple(self.session_run_ids):
            return True
        return time.monotonic() - self.last_session_run_refresh >= self.CODEX_RUN_REFRESH_SECONDS

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        row_key = row_key_value(event.row_key)
        if row_key != current_cursor_row_key(event.data_table):
            return
        if event.data_table.id == "experiments":
            if self.snapshot and any(experiment.key == row_key for experiment in self.snapshot.experiments):
                if row_key != self.selected_exp_key:
                    self.selected_exp_key = row_key
                    self.selected_session_id = None
                    self.render_selection()
            return
        if event.data_table.id == "sessions":
            experiment = self.selected_experiment()
            if experiment and any(session.id == row_key for session in experiment.sessions):
                if row_key != self.selected_session_id:
                    self.selected_session_id = row_key
                    self.start_session_focus_worker()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = row_key_value(event.row_key)
        if event.data_table.id == "experiments":
            self.selected_exp_key = row_key
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

    def format_experiment_stats(self, experiment: Experiment) -> Text:
        parts = []

        worktree_stat = self.worktree_stats.get(experiment.key, "")
        if worktree_stat:
            parts.append(worktree_stat)

        if experiment.plan_lines > 0:
            parts.append(f"[dim]Plan: {experiment.plan_lines}L[/dim]")

        if experiment.outputs_count > 0:
            parts.append(f"[dim]Outs: {experiment.outputs_count}[/dim]")

        if experiment.logs_count > 0:
            parts.append(f"[dim]Logs: {experiment.logs_count}[/dim]")

        return Text.from_markup("  ".join(parts))

    def render_snapshot(self) -> None:
        if self.snapshot is None:
            return

        table = self.query_one("#experiments", DataTable)
        table.clear()
        experiment_keys = {experiment.key for experiment in self.snapshot.experiments}
        self.experiment_run_spinners = {
            exp_key: spinner
            for exp_key, spinner in self.experiment_run_spinners.items()
            if exp_key in experiment_keys
        }
        selected_row = 0
        now = datetime.now().astimezone()
        for index, experiment in enumerate(self.snapshot.experiments):
            row_values = [
                self.experiment_run_indicator(experiment),
            ]
            if self.show_project_column:
                row_values.append(experiment.project_name)
            row_values.extend(
                [
                    experiment.title,
                    Text(experiment.branch, style="dim"),
                    Text(friendly_time(experiment.updated_at, now=now), style="dim"),
                    self.format_experiment_stats(experiment),
                ]
            )
            table.add_row(*row_values, key=experiment.key)
            if experiment.key == self.selected_exp_key:
                selected_row = index
        if self.snapshot.experiments:
            table.move_cursor(row=selected_row, column=0, animate=False)
        self.render_selection()

    def render_experiment_run_indicators(self) -> None:
        if self.snapshot is None:
            return

        table = self.query_one("#experiments", DataTable)
        for experiment in self.snapshot.experiments:
            table.update_cell(
                experiment.key,
                "run",
                self.experiment_run_indicator(experiment),
                update_width=False,
            )

    def render_selection(self) -> None:
        if self.snapshot is None:
            return

        experiment = self.selected_experiment()
        self.query_one("#details", Static).update(self.details_text(experiment))

        self.render_sessions(experiment)
        self.render_links(experiment)
        self.start_session_focus_worker()

    def render_sessions(self, experiment: Optional[Experiment]) -> None:
        sessions = self.query_one("#sessions", DataTable)
        title = self.query_one("#sessions-title", Static)

        if experiment is None:
            self.selected_session_id = None
            sync_table_rows(sessions, (), ("id", "title", "run", "updated"))
            title.update("SESSIONS (0)")
            self.render_codex_focus(unavailable_focus("", "No session selected."))
            return

        title.update("SESSIONS ({0})".format(len(experiment.sessions)))
        session_ids = {session.id for session in experiment.sessions}
        if self.selected_session_id not in session_ids:
            self.selected_session_id = experiment.sessions[0].id if experiment.sessions else None
        if self.selected_session_id is None:
            self.render_codex_focus(unavailable_focus("", "No session selected."))

        selected_row = 0
        now = datetime.now().astimezone()
        rows = []
        for index, session in enumerate(experiment.sessions):
            rows.append(
                (
                    session.id,
                    (
                        session.id,
                        session.title,
                        self.session_run_state(session),
                        friendly_time(session.updated_at or session.created_at, now=now),
                    ),
                )
            )
            if session.id == self.selected_session_id:
                selected_row = index
        sync_table_rows(sessions, rows, ("id", "title", "run", "updated"))
        if experiment.sessions:
            move_table_cursor(sessions, selected_row)

    def render_links(self, experiment: Optional[Experiment]) -> None:
        links = self.query_one("#links", DataTable)
        links.clear()

        if experiment is None:
            rules = self.snapshot.map_config.links if self.snapshot and not self.show_project_column else []
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
        if self.snapshot is None or self.selected_exp_key is None:
            return None
        return next((e for e in self.snapshot.experiments if e.key == self.selected_exp_key), None)

    def project_for_experiment(self, experiment: Experiment) -> Optional[ProjectSnapshot]:
        if self.snapshot is None:
            return None
        return next((project for project in self.snapshot.projects if project.key == experiment.project_key), None)

    def selected_session(self) -> Optional[AgentSession]:
        experiment = self.selected_experiment()
        if experiment is None or self.selected_session_id is None:
            return None
        return next((s for s in experiment.sessions if s.id == self.selected_session_id), None)

    def session_run_state(self, session: AgentSession) -> str:
        return self.session_run_states.get(session.id, UNKNOWN_RUN_STATE)

    def start_session_focus_worker(self) -> None:
        session = self.selected_session()
        if session is None:
            self.cancel_session_focus_worker()
            self.render_codex_focus(unavailable_focus("", "No session selected."))
            return
        if (
            self.session_focus_worker_id == session.id
            and self.session_focus_worker is not None
            and not self.session_focus_worker.is_finished
        ):
            return

        self.cancel_session_focus_worker()
        self.session_focus_worker_id = session.id
        self.render_codex_focus(
            CodexFocusSummary(
                thread_id=session.id,
                state=self.session_run_state(session),
                focus="Loading Codex preview...",
                phase="Reading visible session activity.",
                available=True,
            )
        )
        self.session_focus_worker = self.run_worker(
            self.refresh_session_focus(session.id),
            name="session-focus",
            group="codex-focus",
        )

    def cancel_session_focus_worker(self) -> None:
        if self.session_focus_worker is not None and not self.session_focus_worker.is_finished:
            self.session_focus_worker.cancel()
        self.session_focus_worker = None
        self.session_focus_worker_id = None

    async def refresh_session_focus(self, session_id: str) -> None:
        while self.selected_session_id == session_id:
            try:
                summary = await asyncio.to_thread(self.session_focus_loader, session_id)
            except Exception:
                summary = unavailable_focus(session_id, "Codex preview unavailable.")
            if self.selected_session_id != session_id:
                return
            self.render_codex_focus(summary)
            if summary.state != UNKNOWN_RUN_STATE:
                self.session_run_states[session_id] = summary.state
                self._experiment_has_active_run_cache.clear()
                self.render_experiment_run_indicators()
            await asyncio.sleep(self.session_focus_refresh_seconds(summary))

    def session_focus_refresh_seconds(self, summary: CodexFocusSummary) -> float:
        if summary.state in self.ACTIVE_EXPERIMENT_RUN_STATES:
            return self.CODEX_FOCUS_ACTIVE_REFRESH_SECONDS
        return self.CODEX_FOCUS_IDLE_REFRESH_SECONDS

    def render_codex_focus(self, summary: CodexFocusSummary) -> None:
        self.query_one("#codex-focus", Static).update(summary.focus)

    def codex_focus_placeholder(self) -> str:
        return "Select a session above to view live AI activity."

    def experiment_has_active_run(self, experiment: Experiment) -> bool:
        if experiment.key not in self._experiment_has_active_run_cache:
            self._experiment_has_active_run_cache[experiment.key] = any(
                self.session_run_state(session) in self.ACTIVE_EXPERIMENT_RUN_STATES
                for session in experiment.sessions
            )
        return self._experiment_has_active_run_cache[experiment.key]


    def experiment_run_indicator(self, experiment: Experiment) -> object:
        if not self.experiment_has_active_run(experiment):
            self.experiment_run_spinners.pop(experiment.key, None)
            return ""
        if experiment.key not in self.experiment_run_spinners:
            self.experiment_run_spinners[experiment.key] = Spinner("dots")
        return Padding(self.experiment_run_spinners[experiment.key], (0, 0, 0, 1))

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
        now = datetime.now().astimezone()
        if snapshot is None:
            return "Scanning worktrees and experiments..."

        if self.show_project_column:
            lines = [
                "Projects: {0}".format(len(snapshot.projects)),
                "Experiments: {0}".format(len(snapshot.experiments)),
            ]
        else:
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
                if self.show_project_column:
                    for project in snapshot.projects:
                        lines.append("- {0}: {1}".format(project.name, project.exps_path))
            return "\n".join(lines)

        project = self.project_for_experiment(experiment)
        if self.show_project_column and project is not None:
            lines.extend(
                [
                    "Project: {0}".format(project.name),
                    "Repository: {0}".format(project.root),
                    "Project experiments: {0}".format(project.exps_path),
                    "Map config: {0}".format(project.map_config.path),
                ]
            )
            if project.git_error:
                lines.append("Git error: {0}".format(project.git_error))
            if project.map_config.error:
                lines.append("Map config error: {0}".format(project.map_config.error))
            if not project.map_config.exists:
                lines.append("Map config: missing")
            else:
                lines.append("Map links: {0}".format(len(project.map_config.links)))

        lines.extend(
            [
                "",
                "Experiment: {0}".format(experiment.id),
                "Title: {0}".format(experiment.title),
                "Branch: {0} ({1})".format(experiment.branch, "exists" if experiment.branch_exists else "missing"),
                "Agent: {0}".format(experiment.agent or "unknown"),
                "Created: {0}".format(friendly_time(experiment.created_at, now=now)),
                "Updated: {0}".format(friendly_time(experiment.updated_at, now=now)),
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

    async def refresh_worktree_stats(self, snapshot: Snapshot) -> None:
        async def fetch_stat(experiment: Experiment) -> Tuple[str, str]:
            if not experiment.worktree_exists:
                return experiment.key, ""

            try:
                proc = await asyncio.create_subprocess_exec(
                    "git", "-C", str(experiment.worktree_path), "diff", "HEAD", "--shortstat",
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                stdout, _ = await proc.communicate()
                stat = stdout.decode("utf-8").strip()

                if stat:
                    files_match = re.search(r'(\d+)\s+file', stat)
                    ins_match = re.search(r'(\d+)\s+insertion', stat)
                    del_match = re.search(r'(\d+)\s+deletion', stat)

                    files = files_match.group(1) if files_match else "0"
                    ins = ins_match.group(1) if ins_match else "0"
                    dels = del_match.group(1) if del_match else "0"

                    parts = [f"∑ {files}"]
                    if ins != "0":
                        parts.append(f"[green]+ {ins}[/green]")
                    if dels != "0":
                        parts.append(f"[red]- {dels}[/red]")
                    return experiment.key, " ".join(parts)
                else:
                    proc2 = await asyncio.create_subprocess_exec(
                        "git", "-C", str(experiment.worktree_path), "status", "--porcelain",
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE
                    )
                    stdout2, _ = await proc2.communicate()
                    untracked = len(stdout2.decode("utf-8").strip().splitlines())
                    if untracked > 0:
                        return experiment.key, f"∑ {untracked} (untracked)"
                    return experiment.key, ""
            except Exception:
                return experiment.key, ""

        results = await asyncio.gather(*(fetch_stat(exp) for exp in snapshot.experiments))
        changed = False
        for exp_key, stat in results:
            if self.worktree_stats.get(exp_key) != stat:
                self.worktree_stats[exp_key] = stat
                changed = True

        if changed:
            self.render_worktree_stats()

    def render_worktree_stats(self) -> None:
        if self.snapshot is None:
            return
        table = self.query_one("#experiments", DataTable)
        for exp in self.snapshot.experiments:
            try:
                table.update_cell(exp.key, "stats", self.format_experiment_stats(exp), update_width=True)
            except Exception:
                pass

def row_key_value(row_key: object) -> str:
    return str(getattr(row_key, "value", row_key))


def current_cursor_row_key(table: DataTable) -> Optional[str]:
    if table.row_count == 0 or not table.is_valid_row_index(table.cursor_coordinate.row):
        return None
    try:
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
    except Exception:
        return None
    return row_key_value(row_key)


def ordered_table_row_keys(table: DataTable) -> Tuple[str, ...]:
    return tuple(row_key_value(row.key) for row in table.ordered_rows)


def sync_table_rows(
    table: DataTable,
    rows: Sequence[Tuple[str, Sequence[object]]],
    column_keys: Sequence[str],
) -> None:
    desired_keys = tuple(row_key for row_key, _ in rows)
    if ordered_table_row_keys(table) != desired_keys:
        table.clear()
        for row_key, values in rows:
            table.add_row(*values, key=row_key)
        return

    for row_key, values in rows:
        for column_key, value in zip(column_keys, values):
            table.update_cell(row_key, column_key, value, update_width=True)


def move_table_cursor(table: DataTable, row: int, column: int = 0) -> None:
    cursor = table.cursor_coordinate
    if cursor.row == row and cursor.column == column:
        return
    table.move_cursor(row=row, column=column, animate=False)
