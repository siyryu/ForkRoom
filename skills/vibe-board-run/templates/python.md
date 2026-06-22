# Python Run Update Template

Use this inside temporary Python scaffolding when a run was already created with `vibe-board run start`.

```python
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


TERMINAL = {"succeeded", "failed", "canceled"}
NON_TERMINAL = {"pending", "running", "waiting"}


def update_vibe_run(run_file: str, status: str, completed: Optional[int], total: Optional[int], message: str, estimated_end_at: str = "") -> None:
    path = Path(run_file)
    run = json.loads(path.read_text(encoding="utf-8"))
    if run.get("status") in TERMINAL:
        raise RuntimeError("terminal run cannot be updated")
    if status not in NON_TERMINAL | TERMINAL:
        raise ValueError(f"invalid run status: {status}")
    if status in NON_TERMINAL and not estimated_end_at:
        raise ValueError("estimated_end_at is required for non-terminal run updates")
    if completed is not None and completed < 0:
        raise ValueError("completed must be non-negative")
    if total is not None and total < 0:
        raise ValueError("total must be non-negative")
    if completed is not None and total is not None and completed > total:
        raise ValueError("completed cannot exceed total")

    updated_at = datetime.now().astimezone().replace(microsecond=0).isoformat()
    run["status"] = status
    run["completed"] = completed if completed is not None else run.get("completed")
    run["total"] = total if total is not None else run.get("total")
    run["message"] = message or run.get("message", "")
    run["updated_at"] = updated_at
    if status in TERMINAL:
        run["ended_at"] = updated_at
    else:
        run["estimated_end_at"] = estimated_end_at

    run.setdefault("events", []).append(
        {
            "type": "template-update",
            "status": status,
            "completed": run.get("completed"),
            "total": run.get("total"),
            "message": run.get("message", ""),
            "estimated_end_at": run.get("estimated_end_at", ""),
            "updated_at": updated_at,
        }
    )
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
```

Call it from a loop:

```python
update_vibe_run(".agents/exps/<exp-id>/runs/<run-id>.json", "running", 450, 1000, "Processed 450/1000 rows", "2026-06-22T18:30:00+08:00")
```
