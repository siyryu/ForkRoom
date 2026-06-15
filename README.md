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

Or point it at a repository:

```bash
vibe-board --root /path/to/repo
```

The TUI does not create experiments, worktrees, symlinks, commits, or handoffs. Those workflows are handled by the companion `skills/vibe-board` skill.

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

`sessions` is optional. If a session entry omits `deeplink`, Vibe Board derives `codex://threads/<id>`. A session should appear in exactly one experiment; duplicate ownership is reported as an experiment warning.

Record a Codex session on an experiment manifest with:

```bash
python3 scripts/record_session.py \
  --root . \
  --exp my-experiment \
  --thread-id 019e7831-63b8-7ca2-a4f7-47593e2846ea \
  --title "Initial implementation" \
  --status running
```

The script appends or updates the session in `.agents/exps/<exp-id>/manifest.json`, fills default metadata, derives the Codex deeplink when omitted, and rejects session ids already owned by another experiment.
