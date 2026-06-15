import asyncio
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Static

from .models import Experiment, Snapshot
from .scanner import scan_repository


class VibeBoardApp(App):
    """Read-only dashboard for worktree-backed experiments."""

    AUTO_REFRESH_SECONDS = 2.0

    CSS = """
    Screen {
        layout: vertical;
    }

    #body {
        height: 1fr;
    }

    #experiments-panel {
        width: 58;
        min-width: 42;
        height: 100%;
        border: solid $accent;
    }

    #right-panel {
        width: 1fr;
        height: 100%;
    }

    #details {
        height: 2fr;
        border: solid $accent;
        padding: 1 2;
        overflow-y: auto;
    }

    #links {
        height: 1fr;
        border: solid $accent;
    }

    DataTable {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.snapshot: Optional[Snapshot] = None
        self.selected_exp_id: Optional[str] = None
        self.refresh_worker = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="body"):
            with Vertical(id="experiments-panel"):
                yield Static("Experiments", id="experiments-title")
                yield DataTable(id="experiments")
            with Vertical(id="right-panel"):
                yield Static("Loading repository state...", id="details")
                yield DataTable(id="links")
        yield Footer()

    def on_mount(self) -> None:
        experiments = self.query_one("#experiments", DataTable)
        experiments.add_columns("ID", "Title", "Status", "Branch", "Updated")
        links = self.query_one("#links", DataTable)
        links.add_columns("Source", "Target", "Required", "Status", "Description")
        self.set_interval(self.AUTO_REFRESH_SECONDS, self.action_refresh, name="auto-refresh")
        self.action_refresh()

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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "experiments":
            return
        row_key = event.row_key
        self.selected_exp_id = str(getattr(row_key, "value", row_key))
        self.render_selection()

    def render_snapshot(self) -> None:
        if self.snapshot is None:
            return

        table = self.query_one("#experiments", DataTable)
        table.clear()
        for experiment in self.snapshot.experiments:
            table.add_row(
                experiment.id,
                experiment.title,
                experiment.status,
                experiment.branch,
                experiment.updated_at,
                key=experiment.id,
            )
        self.render_selection()

    def render_selection(self) -> None:
        if self.snapshot is None:
            return

        experiment = self.selected_experiment()
        self.query_one("#details", Static).update(self.details_text(experiment))
        self.render_links(experiment)

    def render_links(self, experiment: Optional[Experiment]) -> None:
        links = self.query_one("#links", DataTable)
        links.clear()

        if experiment is None:
            rules = self.snapshot.map_config.links if self.snapshot else []
            for rule in rules:
                links.add_row(rule.source, rule.target, str(rule.required), "no experiment", rule.description)
            return

        for link in experiment.link_statuses:
            links.add_row(
                link.rule.source,
                link.rule.target,
                str(link.rule.required),
                "{0}: {1}".format(link.status, link.message),
                link.rule.description,
            )

    def selected_experiment(self) -> Optional[Experiment]:
        if self.snapshot is None or self.selected_exp_id is None:
            return None
        for experiment in self.snapshot.experiments:
            if experiment.id == self.selected_exp_id:
                return experiment
        return None

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
            lines.append("Git status: error: {0}".format(snapshot.git_error))
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
                "Status: {0}".format(experiment.status),
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
                "Git status: {0}".format(experiment.git_status),
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
        link_counts = summarize_links(experiment)
        if link_counts:
            lines.extend(["", "Link status: {0}".format(link_counts)])
        return "\n".join(lines)


def summarize_links(experiment: Experiment) -> str:
    counts = {}
    for link in experiment.link_statuses:
        counts[link.status] = counts.get(link.status, 0) + 1
    return ", ".join("{0} {1}".format(value, key) for key, value in sorted(counts.items()))
