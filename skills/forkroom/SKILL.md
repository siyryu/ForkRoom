---
name: forkroom
description: Main entry point and global guardrails for ForkRoom coding experiments. Use this to understand the experiment layout, strict worktree isolation rules, and available sub-commands (init, record, merge).
---

# ForkRoom: Global Guardrails & Overview

This is the central routing and guardrail skill for ForkRoom experiments. ForkRoom manages coding experiments backed by Git worktrees to keep experimental agent work isolated from the main repository.

## 🚦 Strict Worktree Context Guardrails (CRITICAL)

When you are operating on a task that belongs to an experiment (e.g., you are working on an issue and have created an experiment for it):

1. **Default Context**: Treat `.agents/exps/<exp-id>/worktree` as your default repository root. Browsing, editing, testing, and git commands should happen **inside this directory**.
2. **Main Worktree is Read-Only**: Use files in the main worktree (outside `.agents/exps/`) only as read-only context. 
3. **No Unprompted Main Edits**: Require explicit user confirmation before making ANY modification to the main worktree. This includes direct file edits, package-manager lockfile changes, formatting, or git operations.
4. **Symlinks & Secrets**: Never read, print, or commit local secret files (e.g., `.env`, `.pem`). Worktree mapping (handled in `init`) uses absolute symlinks to share these safely.

## 📂 Experiment Layout

Every experiment follows this structure:

```text
.agents/exps/<exp-id>/
  manifest.json
  worktree/      <-- All code changes happen here
  outputs/
  logs/
  runs/
  plan.md        <-- Optional; only when planning is explicitly requested
  handoff.md     <-- Generated during merge review
```

## 🛠️ Available Sub-Commands

Instead of executing the entire lifecycle manually, delegate tasks to the following specialized skills based on the user's request:

*   **`forkroom-init`**
    Use when starting a new experiment. It handles `forkroom init` to create the worktree, branch, and manifest, and automatically sets up local unindexed file symlinks (mapping).
*   **`forkroom-record`**
    Use when the user pastes text containing an experiment ID (usually copied via the TUI's 'c' shortcut) to quickly bind the current AI session to that experiment.
*   **`forkroom-run`**
    Use when a long-running task needs tracked progress, ETA updates, and strict lifecycle management. It handles `forkroom run` plus template-based progress updates inside temporary scaffolding.
*   **`forkroom-merge`**
    Use when an experiment is finished and needs to be merged back into the main repository. It uses a subagent to selectively port ONLY the core solution (discarding scaffolding), commits the changes, and generates a handoff document.

*(If the user's request matches one of these specific actions, directly invoke the corresponding skill.)*
