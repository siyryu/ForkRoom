# ForkRoom

ForkRoom is a read-only terminal dashboard for worktree-backed agent coding experiments.

## Quick install

ForkRoom has two install paths:

- **Standard install (recommended)** installs the TUI from GitHub with `uv`, then copies the Codex skills into the repository where you want to use ForkRoom.
- **Developer install** clones this repository locally and symlinks the skills into another repository, so skill edits in the clone are reflected immediately in the installed skill.

### Standard install (recommended)

Install the TUI from GitHub:

```bash
uv tool install "git+https://github.com/siyryu/forkroom.git"
```

Then install the skills into the repository where Codex should use ForkRoom:

```bash
cd /path/to/your-repo
CODEX_SKILLS_DIR="$PWD/.codex/skills"
FORKROOM_TMP="$(mktemp -d)"

mkdir -p "$CODEX_SKILLS_DIR"
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/siyryu/forkroom.git "$FORKROOM_TMP"
git -C "$FORKROOM_TMP" sparse-checkout set skills
cp -R "$FORKROOM_TMP/skills/." "$CODEX_SKILLS_DIR/"
rm -rf "$FORKROOM_TMP"
```

To install the skills globally instead, use `~/.codex/skills` as the target directory:

```bash
CODEX_SKILLS_DIR="$HOME/.codex/skills"
FORKROOM_TMP="$(mktemp -d)"

mkdir -p "$CODEX_SKILLS_DIR"
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/siyryu/forkroom.git "$FORKROOM_TMP"
git -C "$FORKROOM_TMP" sparse-checkout set skills
cp -R "$FORKROOM_TMP/skills/." "$CODEX_SKILLS_DIR/"
rm -rf "$FORKROOM_TMP"
```

Run the TUI from a repository root:

```bash
forkroom
```

### Developer install

Use the developer install when you want to modify the TUI or the ForkRoom skills locally.

```bash
FORKROOM_REPO="$HOME/Developer/forkroom"
TARGET_REPO="/path/to/your-repo"
CODEX_SKILLS_DIR="$TARGET_REPO/.codex/skills"

git clone https://github.com/siyryu/forkroom.git "$FORKROOM_REPO"
uv tool install --force --editable "$FORKROOM_REPO"

mkdir -p "$CODEX_SKILLS_DIR"
find "$FORKROOM_REPO/skills" -mindepth 1 -maxdepth 1 \
  -exec ln -s {} "$CODEX_SKILLS_DIR" \;
```

For a global developer skill install, set `CODEX_SKILLS_DIR="$HOME/.codex/skills"`.

The developer install uses symlinks instead of copying files, so changes made under `$FORKROOM_REPO/skills` are visible to Codex without reinstalling the skills.

## Usage

For local development of this repository, install it in editable mode:

```bash
pip install -e .
forkroom
```

The dashboard refreshes automatically every two seconds. Press `r` to refresh on demand.
Move the experiment cursor to inspect its details, symlink status, and recorded Codex sessions.
Press `Enter` on an experiment to focus its sessions, then press `Enter` on a session to open its Codex deep link.
When a session is highlighted, the preview panel bolds the latest user command and shows Codex's latest visible update under a branch-style guide.
Long Codex updates are fitted to the preview panel height, with the final ellipsis line included in that height budget.
Press `Esc` to return focus to the experiments table.

The experiments table shows an animated indicator next to any experiment with a recorded session that is active or waiting on approval. The sessions table shows the specific `Run` state for each recorded Codex thread. ForkRoom queries the local Codex App Server and falls back to `unknown` if Codex is unavailable, times out, or cannot read a thread.
The preview panel uses the same local App Server and shows visible session activity only; it does not expose shell/tool command lines or replace opening the full Codex thread for details.

ForkRoom resolves `codex` from `PATH`, then falls back to the macOS Codex.app bundle. Set `FORKROOM_CODEX_BIN` to override the executable path.

Or point it at a repository:

```bash
forkroom --root /path/to/repo
```

Or preview experiments across multiple repositories in one board:

```bash
forkroom --root /path/to/repo-a --root /path/to/repo-b
```

When multiple roots are provided, ForkRoom merges experiments into one table, adds a `Project` column, and sorts the combined list by most recently updated experiment.

The TUI does not create experiments, worktrees, symlinks, commits, or handoffs. Those workflows are handled by CLI subcommands and the `skills/forkroom` skill.

Create an experiment with the deterministic initializer:

```bash
forkroom init \
  --root . \
  --id my-experiment \
  --title "My Experiment" \
  --summary "Explore a focused change in an isolated worktree." \
  --session-title "Initialize my experiment" \
  --thread-id 019e7831-63b8-7ca2-a4f7-47593e2846ea \
  --status running
```

The initializer validates the repository, checks for experiment/branch/worktree conflicts, creates the experiment directories, branch, and worktree, writes `manifest.json`, records the Codex session when `--thread-id` is provided, applies `.forkroom/worktree-map.json`, and prints structured JSON. It does not create `plan.md`; write a plan only when a user asks for one or enters Plan mode.

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

`sessions` is optional. If a session entry omits `deeplink`, ForkRoom derives `codex://threads/<id>`. A session should appear in exactly one experiment; duplicate ownership is reported as an experiment warning. The manifest `status` field is metadata only; the TUI's `Run` column comes from Codex runtime state.

Record a Codex session on an experiment manifest with:

```bash
forkroom record-session \
  --root . \
  --exp my-experiment \
  --thread-id 019e7831-63b8-7ca2-a4f7-47593e2846ea \
  --title "Initial implementation" \
  --status running
```

The command appends or updates the session in `.agents/exps/<exp-id>/manifest.json`, fills default metadata, derives the Codex deeplink when omitted, and rejects session ids already owned by another experiment.

`forkroom init` and `forkroom record-session` intentionally operate on one `--root` at a time, even though the TUI can preview multiple roots.

Track long-running work with an experiment run:

```bash
forkroom run start \
  --root . \
  --exp my-experiment \
  --id train-model \
  --title "Train model" \
  --eta 2h \
  --completed 0 \
  --total 10 \
  --message "Starting training"
```

Each run is stored as `.agents/exps/<exp-id>/runs/<run-id>.json` and belongs to the current Codex session via `CODEX_THREAD_ID`; pass `--session-id` only when the environment does not provide it. A session can own only one active run at a time. Active statuses are `pending`, `running`, and `waiting`; terminal statuses are `succeeded`, `failed`, and `canceled`.

Every non-terminal update must refresh the ETA:

```bash
forkroom run update \
  --root . \
  --exp my-experiment \
  --id train-model \
  --status running \
  --eta "45m" \
  --completed 4 \
  --total 10 \
  --message "Completed epoch 4/10"
```

Finish exactly once:

```bash
forkroom run succeed --root . --exp my-experiment --id train-model --message "Training complete"
```

For temporary scaffolding inside an experiment worktree, use `skills/forkroom-run.md` and the Shell, Python, or Node templates under `skills/forkroom-run/templates/`. Templates directly update an existing run JSON file and append events; they do not create runs, so the session uniqueness check stays centralized in `forkroom run start`.

The legacy `python3 scripts/init_experiment.py` and `python3 scripts/record_session.py` entry points remain as compatibility wrappers when working from the ForkRoom source tree.
