# Shell Run Update Template

Use this inside temporary shell scaffolding when a run was already created with `forkroom run start`.

```bash
update_forkroom_run() {
  run_file="$1"
  status="$2"
  completed="$3"
  total="$4"
  message="$5"
  estimated_end_at="$6"
  updated_at="$(date -Iseconds)"

  if [ "$status" != "succeeded" ] && [ "$status" != "failed" ] && [ "$status" != "canceled" ] && [ -z "$estimated_end_at" ]; then
    echo "estimated_end_at is required for non-terminal run updates" >&2
    return 2
  fi

  RUN_FILE="$run_file" RUN_STATUS="$status" RUN_COMPLETED="$completed" RUN_TOTAL="$total" RUN_MESSAGE="$message" RUN_ETA="$estimated_end_at" RUN_UPDATED_AT="$updated_at" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["RUN_FILE"])
run = json.loads(path.read_text(encoding="utf-8"))
status = os.environ["RUN_STATUS"]
completed = int(os.environ["RUN_COMPLETED"]) if os.environ["RUN_COMPLETED"] else run.get("completed")
total = int(os.environ["RUN_TOTAL"]) if os.environ["RUN_TOTAL"] else run.get("total")
message = os.environ["RUN_MESSAGE"] or run.get("message", "")
eta = os.environ["RUN_ETA"] or run.get("estimated_end_at", "")
updated_at = os.environ["RUN_UPDATED_AT"]

if run.get("status") in {"succeeded", "failed", "canceled"}:
    raise SystemExit("terminal run cannot be updated")
if status not in {"pending", "running", "waiting", "succeeded", "failed", "canceled"}:
    raise SystemExit("invalid run status")
if status not in {"succeeded", "failed", "canceled"} and not eta:
    raise SystemExit("estimated_end_at is required for non-terminal run updates")

run["status"] = status
run["completed"] = completed
run["total"] = total
run["message"] = message
run["updated_at"] = updated_at
if status in {"succeeded", "failed", "canceled"}:
    run["ended_at"] = updated_at
else:
    run["estimated_end_at"] = eta

run.setdefault("events", []).append({
    "type": "template-update",
    "status": status,
    "completed": completed,
    "total": total,
    "message": message,
    "estimated_end_at": eta,
    "updated_at": updated_at,
})
tmp = path.with_name("." + path.name + ".tmp")
tmp.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
tmp.replace(path)
PY
}
```

Call it from a loop:

```bash
update_forkroom_run ".forkroom/exps/<exp-id>/runs/<run-id>.json" running 45 100 "Processed 45/100 items" "2026-06-22T18:30:00+08:00"
```
