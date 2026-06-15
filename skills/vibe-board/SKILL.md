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
  plan.md
  worktree/
  outputs/
  logs/
  handoff.md
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

`sessions` is optional when no Codex conversation has been associated yet. Use it to record Codex conversation sessions that belong to the experiment:

```json
{
  "id": "019e7831-63b8-7ca2-a4f7-47593e2846ea",
  "title": "Initial implementation",
  "agent": "codex",
  "status": "running",
  "created_at": "2026-06-15T10:00:00+08:00",
  "updated_at": "2026-06-15T10:30:00+08:00",
  "deeplink": "codex://threads/019e7831-63b8-7ca2-a4f7-47593e2846ea"
}
```

Every Codex session can belong to only one experiment. When an experiment creates a new session, append it to that experiment's `manifest.json` `sessions` list. When a Codex session starts a new experiment, write that session into the new experiment's `manifest.json` before handing it off. If `deeplink` is omitted, the TUI derives `codex://threads/<session-id>`.

## Create An Experiment

1. Confirm the repository is clean enough for a parallel experiment with `git status --short`.
2. Choose a lowercase hyphenated `<exp-id>` and create `.agents/exps/<exp-id>/outputs` and `.agents/exps/<exp-id>/logs`.
3. Create branch `agents/<exp-id>` from the current main worktree HEAD.
4. Create the worktree at `.agents/exps/<exp-id>/worktree`.
5. Write `manifest.json` and `plan.md` in the experiment directory. If the current Codex thread is the session starting this experiment, include it in `manifest.json` `sessions`.
6. Apply `.vibe-board/worktree-map.json` by creating symlinks in the experiment worktree.
7. Do all experiment code changes inside `.agents/exps/<exp-id>/worktree`, not in the main worktree.

Use non-interactive git commands. Do not commit unless the user explicitly asks.

Recommended command shape:

```bash
mkdir -p ".agents/exps/<exp-id>/outputs" ".agents/exps/<exp-id>/logs"
git branch "agents/<exp-id>" HEAD
git worktree add ".agents/exps/<exp-id>/worktree" "agents/<exp-id>"
```

If the branch or worktree already exists, stop and explain the conflict rather than reusing it silently.

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
