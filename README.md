# Vibe Board

Vibe Board is a read-only terminal dashboard for worktree-backed agent coding experiments.

Run it from a repository root:

```bash
pip install -e .
vibe-board
```

The dashboard refreshes automatically every two seconds. Press `r` to refresh on demand.
Move the experiment cursor to inspect its details, symlink status, and recorded Codex sessions.
Press `Enter` on an experiment to focus its sessions, then press `Enter` on a session to open its Codex deep link.
Press `Esc` to return focus to the experiments table.

The experiments table shows an animated indicator next to any experiment with a recorded session that is active or waiting on approval. The sessions table shows the specific `Run` state for each recorded Codex thread. Vibe Board queries the local Codex App Server and falls back to `unknown` if Codex is unavailable, times out, or cannot read a thread.

Vibe Board resolves `codex` from `PATH`, then falls back to the macOS Codex.app bundle. Set `VIBE_BOARD_CODEX_BIN` to override the executable path.

Or point it at a repository:

```bash
vibe-board --root /path/to/repo
```

The TUI does not create experiments, worktrees, symlinks, commits, or handoffs. Those workflows are handled by CLI subcommands and the `skills/vibe-board` skill.

Create an experiment with the deterministic initializer:

```bash
vibe-board init \
  --root . \
  --id my-experiment \
  --title "My Experiment" \
  --summary "Explore a focused change in an isolated worktree." \
  --session-title "Initialize my experiment" \
  --thread-id 019e7831-63b8-7ca2-a4f7-47593e2846ea \
  --status running
```

The initializer validates the repository, checks for experiment/branch/worktree conflicts, creates the experiment directories, branch, and worktree, writes `manifest.json`, records the Codex session when `--thread-id` is provided, applies `.vibe-board/worktree-map.json`, and prints structured JSON. It does not create `plan.md`; write a plan only when a user asks for one or enters Plan mode.

Experiments can record the Codex conversations that belong to them in `manifest.json`:

```json
{
  "id": "short-exp-id",
  "sessions": [
    {
      "id": "019e7831-63b8-7ca2-a4f7-47593e2846ea",
      "title": "Initial implementation",
      "agent": "codex",
      "status": "running",
      "created_at": "2026-06-15T10:00:00+08:00",
      "updated_at": "2026-06-15T10:30:00+08:00",
      "deeplink": "codex://threads/019e7831-63b8-7ca2-a4f7-47593e2846ea"
    }
  ]
}
```

`sessions` is optional. If a session entry omits `deeplink`, Vibe Board derives `codex://threads/<id>`. A session should appear in exactly one experiment; duplicate ownership is reported as an experiment warning. The manifest `status` field is metadata only; the TUI's `Run` column comes from Codex runtime state.

Record a Codex session on an experiment manifest with:

```bash
vibe-board record-session \
  --root . \
  --exp my-experiment \
  --thread-id 019e7831-63b8-7ca2-a4f7-47593e2846ea \
  --title "Initial implementation" \
  --status running
```

The command appends or updates the session in `.agents/exps/<exp-id>/manifest.json`, fills default metadata, derives the Codex deeplink when omitted, and rejects session ids already owned by another experiment.

The legacy `python3 scripts/init_experiment.py` and `python3 scripts/record_session.py` entry points remain as compatibility wrappers when working from the Vibe Board source tree.
