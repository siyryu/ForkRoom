---
name: forkroom:record
description: Bind the current AI session to an existing experiment. Triggered when the user pastes experiment info copied via the TUI 'c' shortcut.
---

# ForkRoom: Record Session

Use this skill when the user pastes experiment information (usually copied from the ForkRoom TUI using the `c` shortcut) and wants to associate the current AI conversation with that experiment.

## Steps

1. **Extract Data**: Parse the user's pasted text to extract the `<exp-id>` and optionally the experiment title.
2. **Identify Session**: Read `CODEX_THREAD_ID` from the current environment to get the `<codex-thread-id>`. If it is unavailable, warn the user that the session ID cannot be automatically determined.
3. **Record**: Run the following command to bind the session:
   ```bash
   forkroom record-session \
     --root . \
     --exp "<exp-id>" \
     --thread-id "<codex-thread-id>" \
     --title "<session-title>" \
     --status running
   ```
   *(Use a concise title summarizing the current goal for `<session-title>` if not explicitly provided).*

## Output
Keep the response extremely brief. E.g., "✅ Successfully bound current session to experiment `<exp-id>`." Do not explain the steps taken unless an error occurred.