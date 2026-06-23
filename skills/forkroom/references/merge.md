# ForkRoom: Selective Merge & Handoff

Use this reference when an experiment is completed and needs to be merged back into the main repository.

Critical merge philosophy: do not blindly `git merge` or copy the entire experiment worktree. Experiments typically contain scaffolding, debugging logs, mock data, and one-off scripts used for testing. Selectively port only the necessary production-ready code that solves the original problem.

## 1. Subagent Review & Selection (Required)
Before making any changes to the main worktree, spawn a subagent using available multi-agent tooling to analyze the experiment.

Prompt the subagent to:

1. Read the experiment's `manifest.json`, `plan.md`, and the `git diff` of the experiment worktree.
2. Categorize the changes into "Core Solution" (code that must be kept) and "Scaffolding/Temp/Debug" (code to be discarded).
3. Draft a precise plan of which files/functions need to be ported to the main worktree.
4. Draft a professional commit message and a summary for the handoff document.

## 2. Selective Porting (Main Agent)
1. Review the subagent's analysis.
2. Manually edit or write the specific files in the **main worktree** to integrate the "Core Solution" changes.
3. Explicitly ignore any scaffolding, temporary files, or local-only symlink targets (like `.env`).
4. Preserve any unrelated user changes that might exist in the main worktree.

## 3. Commit
1. Stage ONLY the specific files you modified in the main worktree: `git add <file1> <file2>` (Do not use `git add .`).
2. Commit the changes using the message drafted by the subagent. Ensure the commit message includes the experiment ID suffix. For example:
   `git commit -m "feat: <description> [ForkRoom: <exp-id>]"`
3. Retrieve the newly created Commit ID:
   `git rev-parse HEAD`

## 4. Handoff Generation
Generate or update `.forkroom/exps/<exp-id>/handoff.md`. The document MUST include:
- The experiment goal.
- The worktree path and branch name.
- A summary of the *selectively merged* files (and what was intentionally left behind).
- The Commit ID (`git rev-parse HEAD` result) so the user can easily verify or rollback.
- Any caveats or manual follow-up instructions.
*(Never include secret values in this file).*

## Output
Summarize the successful selective merge to the user, highlighting the Commit ID, what core logic was ported, and confirming that scaffolding was discarded.
