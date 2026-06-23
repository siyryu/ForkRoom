---
name: forkroom
description: Main layered entry point and global guardrails for ForkRoom coding experiments. Use when starting an experiment, binding a session to an existing experiment, tracking a long-running run, or selectively merging an experiment back into the main worktree.
---

# ForkRoom

Use this as the single entry point for ForkRoom experiments. Load the relevant reference file for the user's requested action, then follow that subworkflow.

ForkRoom manages coding experiments backed by Git worktrees to keep experimental agent work isolated from the main repository.

## Strict Worktree Guardrails

When you are operating on a task that belongs to an experiment (e.g., you are working on an issue and have created an experiment for it):

1. Treat `.forkroom/exps/<exp-id>/worktree` as the default repository root. Browse, edit, test, and run git commands inside this directory.
2. Use the main worktree outside `.forkroom/exps/` as read-only context unless the merge workflow explicitly says otherwise.
3. Require explicit user confirmation before modifying the main worktree outside the merge workflow.
4. Never read, print, or commit secret files such as `.env` or `*.pem`. Worktree mapping uses symlinks so local-only files can be shared without exposing contents.

## Experiment Layout

Every experiment follows this structure:

```text
.forkroom/exps/<exp-id>/
  manifest.json
  worktree/      <-- All code changes happen here
  outputs/
  logs/
  runs/
  plan.md        <-- Optional; only when planning is explicitly requested
  handoff.md     <-- Generated during merge review
```

## Routing

Read exactly the reference needed for the task:

- Start a new experiment: read `references/init.md`.
- Bind the current session to an existing experiment: read `references/record.md`.
- Track a long-running task with run status and ETA updates: read `references/run.md`.
- Merge a finished experiment back into the main worktree: read `references/merge.md`.

For run progress templates, read one of:

- Shell scaffolding: `references/run-template-shell.md`.
- Python scaffolding: `references/run-template-python.md`.
- Node.js scaffolding: `references/run-template-node.md`.
