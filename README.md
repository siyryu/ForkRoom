# Vibe Board

Vibe Board is a read-only terminal dashboard for worktree-backed agent coding experiments.

Run it from a repository root:

```bash
pip install -e .
vibe-board
```

The dashboard refreshes automatically every two seconds. Press `r` to refresh on demand.

Or point it at a repository:

```bash
vibe-board --root /path/to/repo
```

The TUI does not create experiments, worktrees, symlinks, commits, or handoffs. Those workflows are handled by the companion `skills/vibe-board` skill.
