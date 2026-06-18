---
name: vibe-board:init
description: Create a new Vibe Board experiment worktree and automatically map local unindexed files (like .env) to the isolated environment.
---

# Vibe Board: Initialize Experiment

Use this skill to create a new coding experiment isolated from the main worktree and set up its local environment mapping automatically.

## 1. Setup the Experiment
1. Extract or derive a lowercase hyphenated `<exp-id>`, a title, a one-sentence summary, and a session title from the user's request.
2. Read `CODEX_THREAD_ID` from the current environment if it is available.
3. Execute the initializer (delegate to a subagent if requested):
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
   *Omit `--thread-id` if unavailable.*

## 2. Auto-Map Unindexed Local Files (Map phase)
After initialization, you must map local unindexed files to ensure the experiment worktree is immediately runnable.
1. Read `.vibe-board/worktree-map.json`.
2. For each rule in the map (containing `source`, `target`, `required`, and `description`):
   - Resolve `source` relative to the main repository root.
   - Resolve `target` relative to the experiment worktree root (`.agents/exps/<exp-id>/worktree/`).
   - If `source` is missing and `required` is true, stop and report the missing local prerequisite.
   - If `target` already exists, report the conflict and skip.
   - Create an absolute symlink: `ln -s "$(pwd)/<source>" ".agents/exps/<exp-id>/worktree/<target>"`
3. Do NOT read, print, or commit the contents of secret files (e.g., `.env`, `*.pem`).

## Guardrails
- **All code changes for this experiment must happen inside `.agents/exps/<exp-id>/worktree`.**
- Do not create a `plan.md` unless explicitly asked.
- Provide a concise summary of the created experiment and mapped files to the user.