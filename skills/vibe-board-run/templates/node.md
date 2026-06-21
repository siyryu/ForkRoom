# Node Run Update Template

Use this inside temporary Node.js scaffolding when a run was already created with `vibe-board run start`.

```js
const fs = require("fs");

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);
const NON_TERMINAL = new Set(["pending", "running", "waiting"]);

function updateVibeRun(runFile, status, progress, message, estimatedEndAt = "") {
  const run = JSON.parse(fs.readFileSync(runFile, "utf8"));
  if (TERMINAL.has(run.status)) {
    throw new Error("terminal run cannot be updated");
  }
  if (!TERMINAL.has(status) && !NON_TERMINAL.has(status)) {
    throw new Error(`invalid run status: ${status}`);
  }
  if (NON_TERMINAL.has(status) && !estimatedEndAt) {
    throw new Error("estimated_end_at is required for non-terminal run updates");
  }
  if (progress !== null && progress !== undefined && (progress < 0 || progress > 100)) {
    throw new Error("progress must be between 0 and 100");
  }

  const updatedAt = new Date().toISOString();
  run.status = status;
  run.progress = progress ?? run.progress;
  run.message = message || run.message || "";
  run.updated_at = updatedAt;
  if (TERMINAL.has(status)) {
    run.ended_at = updatedAt;
  } else {
    run.estimated_end_at = estimatedEndAt;
  }

  run.events = run.events || [];
  run.events.push({
    type: "template-update",
    status,
    progress: run.progress,
    message: run.message,
    estimated_end_at: run.estimated_end_at || "",
    updated_at: updatedAt,
  });

  const tmp = `${runFile}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(run, null, 2)}\n`, "utf8");
  fs.renameSync(tmp, runFile);
}
```

Call it from a loop:

```js
updateVibeRun(".agents/exps/<exp-id>/runs/<run-id>.json", "running", 45, "Processed 45%", "2026-06-22T18:30:00+08:00");
```
