# ForkRoom

ForkRoom is a replacement for traditional worktrees that helps you run multiple coding ideas in isolated workspaces, fully in parallel and without tears.
When you start a new experiment, it keeps code changes, plans, runs, outputs, and logs together so every trial has one place to live.
It is a minimal implementation of an AI-native coding ecosystem: you keep full control of everything and can use any coding agent you like, including Codex, Claude Code, and others.

## Install

1. Open your project directory.
2. Run one command:

```bash
uvx --from git+https://github.com/siyryu/forkroom.git forkroom install
```

This installs the `forkroom` CLI and the ForkRoom skills for the current project.

## Usage

Use ForkRoom from the repository root where you want experiments to live.

### Create an experiment

Ask your coding agent to create a ForkRoom experiment, or run:

```bash
forkroom init \
  --root . \
  --id my-experiment \
  --title "My Experiment" \
  --summary "Explore a focused change in an isolated workspace." \
  --session-title "Initial session" \
  --thread-id "$CODEX_THREAD_ID" \
  --status running
```

This creates `.forkroom/exps/my-experiment/worktree`, a `forkroom/my-experiment` branch, and a manifest that keeps the experiment together. Omit `--thread-id` if your current agent does not provide one.

### Continue an experiment in another session

Run `forkroom`, highlight the experiment, press `c` to copy its info, then paste it into a new agent session and ask it to continue that experiment.

You can also bind the new session manually:

```bash
forkroom record-session \
  --root . \
  --exp my-experiment \
  --thread-id "$CODEX_THREAD_ID" \
  --title "Continue my experiment" \
  --status running
```

Continue the work inside `.forkroom/exps/my-experiment/worktree`.

### Merge an experiment

When an experiment is ready, ask your coding agent to merge experiment `my-experiment` back to `main`, commit it, and push.

ForkRoom's merge flow selectively ports the finished code into the main worktree instead of blindly merging the experiment branch. The final steps should look like:

```bash
git switch main
git add <merged-files>
git commit -m "feat: describe the change [ForkRoom: my-experiment]"
git push
```

The experiment should also get a `.forkroom/exps/my-experiment/handoff.md` file with the commit ID, merged files, and any follow-up notes.

## Contribute

Clone ForkRoom and install the local CLI in editable mode:

```bash
FORKROOM_REPO="$HOME/Developer/forkroom"

git clone https://github.com/siyryu/forkroom.git "$FORKROOM_REPO"
cd "$FORKROOM_REPO"
uv tool install --force --editable .
```

Link the local skills into a project you use for testing:

```bash
forkroom install --root /path/to/your-project --source . --link-skills --no-tool-install
```

Run the tests before sending changes:

```bash
uv run --with pytest python -m pytest
```
