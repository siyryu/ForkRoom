---
name: vibe-board
description: Manage Vibe Board coding experiments backed by Git worktrees. Use when Codex needs to create a new experiment under .agents/exps, set up the experiment worktree and required local symlinks from .vibe-board/worktree-map.json, write experiment plans/outputs/logs/handoffs, or merge-review an experiment back into the main repository without automatically committing.
---

# Vibe Board

## Overview

Use this skill to keep agent coding experiments isolated from the main worktree. The Vibe Board TUI is read-only; this skill is responsible for the workflows that create experiments, create worktrees, link local-only files, and prepare merge-review handoffs.

Never write secrets or local key contents into plans, logs, manifests, or handoffs.

## Experiment Layout

Use this layout for every experiment:

```text
.agents/exps/<exp-id>/
  manifest.json
  worktree/
  outputs/
  logs/
  plan.md      # optional; only when planning is requested
  handoff.md   # optional; usually generated during merge review
```

Use branch names in the form `agents/<exp-id>`. Keep `.agents/exps/` ignored by the main repository.

`manifest.json` must contain at least:

```json
{
  "id": "short-exp-id",
  "title": "Human readable title",
  "status": "draft",
  "branch": "agents/short-exp-id",
  "created_at": "2026-06-13T00:00:00+08:00",
  "updated_at": "2026-06-13T00:00:00+08:00",
  "summary": "One sentence experiment summary",
  "agent": "codex"
}
```

Allowed statuses are `draft`, `running`, `ready`, `handoff`, `merged`, and `archived`.

`sessions` is optional when no Codex conversation has been associated yet. Record Codex conversation sessions with `vibe-board record-session` instead of hand-editing session JSON. The command fills session defaults, derives `codex://threads/<thread-id>` when no deeplink is provided, updates an existing session entry instead of duplicating it, and refuses to record a session already owned by another experiment.

Use this command after the experiment manifest exists and the Codex thread id is known:

```bash
vibe-board record-session \
  --root . \
  --exp "<exp-id>" \
  --thread-id "<codex-thread-id>" \
  --title "<session-title>" \
  --status running
```

If the current Codex thread is the session starting this experiment, record it before handing the experiment back to the user. If the thread id cannot be determined, do not invent one; leave `sessions` absent and mention the missing association.

## Create An Experiment

Default to the deterministic initializer instead of manually running each setup command. The main agent should:

1. Choose or derive a lowercase hyphenated `<exp-id>`, a title, a one-sentence summary, and a session title from the user's request.
2. Read `CODEX_THREAD_ID` from the current environment if it is available. Do not invent a thread id, and do not ask the subagent to discover it.
3. Delegate the initialization to a subagent when the user asks for subagent-based setup. The subagent should only call `vibe-board init` with the provided parameters and return the command's structured result plus a concise status.
4. Summarize the result for the user.

The initializer is responsible for the deterministic workflow:

```bash
vibe-board init \
  --root . \
  --id "<exp-id>" \
  --title "<title>" \
  --summary "<summary>" \
  --session-title "<session-title>" \
  --thread-id "<codex-thread-id>" \
  --status running
```

Omit `--thread-id` when the current Codex thread id is unavailable. The command confirms the repository is clean enough for a parallel experiment, checks for existing experiment directories, branches, and worktrees, creates `.agents/exps/<exp-id>/outputs` and `.agents/exps/<exp-id>/logs`, creates branch `agents/<exp-id>` from the current main worktree HEAD, creates the worktree at `.agents/exps/<exp-id>/worktree`, writes `manifest.json`, records the Codex session when a thread id is provided, applies `.vibe-board/worktree-map.json`, and emits JSON describing paths, warnings, and failures.

Do not create `plan.md` during default initialization. Write `plan.md` only when the user explicitly asks for a plan, enters Plan mode, or provides plan content to save. Do all experiment code changes inside `.agents/exps/<exp-id>/worktree`, not in the main worktree. Use non-interactive git commands. Do not commit unless the user explicitly asks.

If the branch or worktree already exists, stop and explain the conflict rather than reusing it silently.

## Edit Experiment Files

When editing experiment code with Codex's `apply_patch` tool, make every patch filename explicitly point into the experiment worktree. `apply_patch` does not take a shell `workdir`, so a bare path such as `skills/vibe-board/SKILL.md` is resolved from the Codex thread's current repository root and can modify the main worktree instead of the experiment worktree.

## Apply Worktree Mapping

Read `.vibe-board/worktree-map.json`. Each rule has `source`, `target`, `required`, and `description`.

For each rule:

1. Resolve `source` relative to the main repository root.
2. Resolve `target` relative to the experiment worktree root.
3. Refuse paths that escape their roots.
4. If `source` is missing and `required` is true, stop and report the missing local prerequisite.
5. If `target` already exists, do not overwrite it; report the conflict.
6. Create a symlink from `target` to `source`.

Do not read or print the contents of `.env`, `.env.*`, `*.pem`, `*.key`, or other local secret files.

Prefer absolute symlink targets so the TUI can compare links reliably:

```bash
ln -s "/absolute/path/to/source" ".agents/exps/<exp-id>/worktree/<target>"
```

## Merge Review

When asked to merge-review an experiment:

1. Read the experiment `manifest.json`, `plan.md`, and `handoff.md` if present.
2. Inspect `git status --short` and diffs inside the experiment worktree.
3. Integrate the intended changes into the main worktree manually and conservatively.
4. Preserve unrelated user changes in the main worktree.
5. Do not copy local-only symlink targets or secret contents into tracked files.
6. Do not commit unless the user explicitly asks.

If `handoff.md` is missing, generate one in the experiment directory with the goal, worktree path, branch, changed files summary, mapping status, merge instructions, and caveats. Never include secret values.
