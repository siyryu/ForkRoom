# Node Run Update Template

Use this inside temporary Node.js scaffolding when a run was already created with `forkroom run start`.

```js
const fs = require("fs");

const TERMINAL = new Set(["succeeded", "failed", "canceled"]);
const NON_TERMINAL = new Set(["pending", "running", "waiting"]);

function updateForkRoomRun(runFile, status, completed, total, message, estimatedEndAt = "") {
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
  if (completed !== null && completed !== undefined && completed < 0) {
    throw new Error("completed must be non-negative");
  }
  if (total !== null && total !== undefined && total < 0) {
    throw new Error("total must be non-negative");
  }
  if (completed !== null && completed !== undefined && total !== null && total !== undefined && completed > total) {
    throw new Error("completed cannot exceed total");
  }

  const updatedAt = new Date().toISOString();
  run.status = status;
  run.completed = completed ?? run.completed;
  run.total = total ?? run.total;
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
    completed: run.completed,
    total: run.total,
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
updateForkRoomRun(".forkroom/exps/<exp-id>/runs/<run-id>.json", "running", 45, 100, "Processed 45/100 items", "2026-06-22T18:30:00+08:00");
```
