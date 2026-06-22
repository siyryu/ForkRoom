---
name: forkroom:run
description: Track a long-running ForkRoom run with strict lifecycle updates, ETA refreshes, and optional template-based progress writes.
---

# ForkRoom: Track a Run

Use this skill when a task will take long enough that the user benefits from progress, status, and ETA updates. Examples include package installation, model training, plan execution, migrations, crawlers, test sweeps, or any loop that produces incremental progress.

## Default Flow

1. Create or bind the current session's only active run:
   ```bash
   forkroom run start \
     --root . \
     --exp "<exp-id>" \
     --id "<run-id>" \
     --title "<human title>" \
     --eta "<iso-time-or-duration>" \
     --completed 0 \
     --total "<total-items>" \
     --message "Starting"
   ```
   `forkroom run start` reads `CODEX_THREAD_ID` by default. Pass `--session-id` only when the environment does not provide it.
2. Start a dedicated progress-tracking subagent by default. Its sole job is to watch the long-running task and update the run.
3. Every non-terminal update must refresh `estimated_end_at`:
   ```bash
   forkroom run update \
     --root . \
     --exp "<exp-id>" \
     --id "<run-id>" \
     --eta "30m" \
     --completed 450 \
     --total 1000 \
     --message "Processed 450/1000 items"
   ```
4. Finish with exactly one terminal state:
   ```bash
   forkroom run succeed --root . --exp "<exp-id>" --id "<run-id>" --message "Completed"
   ```
   Use `fail` for errors and `cancel` for intentional stops.

## Rules

- A Codex session may own only one active run at a time.
- Templates must only update an existing run JSON file. They must not create runs.
- Non-terminal statuses are `pending`, `running`, and `waiting`; each requires `estimated_end_at`.
- Terminal statuses are `succeeded`, `failed`, and `canceled`; terminal runs must not be updated again.
- If a subagent cannot be started, the main agent is responsible for the same update cadence.

## Template Selection

Use the templates in `skills/forkroom-run/templates/` when writing temporary scaffold code inside an experiment worktree:

- `shell.md` for shell scripts and installation loops.
- `python.md` for training, ETL, crawling, or data-processing loops.
- `node.md` for JavaScript/TypeScript scripts.

Each template directly updates the existing run JSON file, appends an event, writes atomically, and preserves the lifecycle constraints above.
