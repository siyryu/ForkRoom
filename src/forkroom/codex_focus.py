import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from .codex_status import (
    UNKNOWN_RUN_STATE,
    CodexRunInfo,
    CodexStatusError,
    JsonRpcProcess,
    codex_status_commands,
    parse_latest_turn_status,
    parse_thread_status,
    resolve_codex_bin,
    summarize_run_state,
)


DEFAULT_FOCUS = "Codex activity is not available."
DEFAULT_PHASE = "Open Codex for details."


@dataclass(frozen=True)
class CodexFocusSummary:
    thread_id: str
    state: str
    focus: str
    phase: str
    updated_at: str = ""
    available: bool = True
    last_user_command: str = ""
    codex_update: str = ""


def load_codex_focus(thread_id: str, timeout_seconds: float = 4.0) -> CodexFocusSummary:
    normalized_thread_id = thread_id.strip()
    if not normalized_thread_id:
        return unavailable_focus("", "No session selected.")

    codex_bin = resolve_codex_bin()
    if not codex_bin:
        return unavailable_focus(normalized_thread_id)

    for command in codex_status_commands(codex_bin):
        try:
            return load_codex_focus_with_command(command, normalized_thread_id, timeout_seconds)
        except CodexStatusError:
            continue
    return unavailable_focus(normalized_thread_id)


def load_codex_focus_with_command(
    command: Sequence[str],
    thread_id: str,
    timeout_seconds: float,
) -> CodexFocusSummary:
    deadline = time.monotonic() + timeout_seconds
    client = JsonRpcProcess(command)
    try:
        client.request(
            {
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {
                        "name": "forkroom_focus",
                        "title": "ForkRoom Focus",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            },
            request_id=1,
            deadline=deadline,
        )
        client.notify({"method": "initialized", "params": {}})
        thread_result = client.request(
            {
                "method": "thread/read",
                "id": 2,
                "params": {"threadId": thread_id, "includeTurns": False},
            },
            request_id=2,
            deadline=deadline,
        )
        turns_result = client.request(
            {
                "method": "thread/turns/list",
                "id": 3,
                "params": {"threadId": thread_id, "limit": 6, "itemsView": "full"},
            },
            request_id=3,
            deadline=deadline,
        )
        return summarize_codex_focus(thread_id, thread_result, turns_result)
    finally:
        client.close()


def summarize_codex_focus(
    thread_id: str,
    thread_result: Mapping[str, Any],
    turns_result: Mapping[str, Any],
) -> CodexFocusSummary:
    thread = mapping_value(thread_result.get("thread"))
    turns = list_value(turns_result.get("data"))
    latest_turn = mapping_value(turns[0]) if turns else {}
    latest_items = list_value(latest_turn.get("items"))
    thread_status, active_flags = parse_thread_status(thread_result)
    turn_status, turn_error, turn_completed = parse_latest_turn_status(turns_result)
    state = summarize_run_state(
        CodexRunInfo(
            thread_status=thread_status,
            turn_status=turn_status,
            turn_error=turn_error,
            turn_completed=turn_completed,
            active_flags=active_flags,
        )
    )
    last_user_command = latest_user_command(turns)
    codex_update = codex_update_from_activity(turns)
    focus = render_focus(last_user_command, codex_update)
    phase = phase_from_activity(state, turn_status, active_flags, turn_error, latest_items)
    updated_at = updated_at_from_activity(thread, latest_turn)
    return CodexFocusSummary(
        thread_id=thread_id,
        state=state,
        focus=focus,
        phase=phase,
        updated_at=updated_at,
        available=True,
        last_user_command=last_user_command,
        codex_update=codex_update,
    )


def unavailable_focus(thread_id: str, focus: str = DEFAULT_FOCUS) -> CodexFocusSummary:
    return CodexFocusSummary(
        thread_id=thread_id,
        state=UNKNOWN_RUN_STATE,
        focus=focus,
        phase=DEFAULT_PHASE,
        available=False,
    )


def focus_from_activity(turns: Sequence[Any]) -> str:
    return render_focus(latest_user_command(turns), codex_update_from_activity(turns))


def codex_update_from_activity(turns: Sequence[Any]) -> str:
    agent_text = latest_agent_text(turns)
    if agent_text:
        return agent_text

    latest_turn = mapping_value(turns[0]) if turns else {}
    item_phase = phase_from_items(list_value(latest_turn.get("items")))
    if item_phase:
        return sentence_case(item_phase) + "."

    return "No visible Codex update yet."


def render_focus(last_user_command: str, codex_update: str) -> str:
    command = clean_text(last_user_command)
    update = clean_text(codex_update)
    if command and update:
        return "Last command:\n{0}\n\nCodex update:\n{1}".format(command, update)
    if command:
        return "Last command:\n{0}".format(command)
    return update


def phase_from_activity(
    state: str,
    turn_status: str,
    active_flags: Sequence[str],
    turn_error: str,
    items: Sequence[Any],
) -> str:
    if "waitingOnApproval" in active_flags or state == "waiting":
        return "waiting for user approval"
    if state in {"error", "failed"} or turn_error:
        return "needs attention"

    latest_text = latest_agent_text_from_items(items)
    text_phase = phase_from_text(latest_text)
    if text_phase:
        return text_phase

    item_phase = phase_from_items(items)
    if item_phase:
        return item_phase

    if state == "active" or turn_status == "inProgress":
        return "working through the current turn"
    if state == "completed":
        return "last turn completed"
    if state in {"idle", "notLoaded"}:
        return "idle after the last turn"
    return "activity state unavailable"


def phase_from_text(text: str) -> str:
    lowered = text.lower()
    if contains_any(lowered, ("test", "verify", "pytest", "check", "验证", "测试")):
        return "verifying the change"
    if contains_any(lowered, ("edit", "implement", "patch", "wire", "add", "change", "实现", "新增", "接入", "改")):
        return "implementing changes"
    if contains_any(lowered, ("inspect", "read", "search", "look", "gather", "确认", "读取", "搜索", "看")):
        return "gathering context"
    if contains_any(lowered, ("plan", "approach", "design", "讨论", "方案", "计划", "拆")):
        return "shaping the approach"
    if contains_any(lowered, ("summar", "final", "wrap", "总结", "收尾")):
        return "summarizing the result"
    return ""


def phase_from_items(items: Sequence[Any]) -> str:
    item_types = []
    for item in items:
        if isinstance(item, Mapping):
            item_types.append(string_value(item.get("type")).lower())
    joined = " ".join(item_types)
    if contains_any(joined, ("patch", "edit", "filechange")):
        return "implementing changes"
    if contains_any(joined, ("tool", "function", "command", "exec", "bash")):
        return "working through implementation details"
    return ""


def latest_agent_text(turns: Sequence[Any]) -> str:
    for raw_turn in turns:
        turn = mapping_value(raw_turn)
        text = latest_agent_text_from_items(list_value(turn.get("items")))
        if text:
            return text
    return ""


def latest_user_command(turns: Sequence[Any]) -> str:
    for raw_turn in turns:
        turn = mapping_value(raw_turn)
        text = latest_user_command_from_items(list_value(turn.get("items")))
        if text:
            return text
    return ""


def latest_user_command_from_items(items: Sequence[Any]) -> str:
    for item in reversed(items):
        if not is_item_type(item, "userMessage"):
            continue
        text = user_message_text(mapping_value(item))
        if text:
            return text
    return ""


def user_message_text(item: Mapping[str, Any]) -> str:
    direct_text = clean_text(string_value(item.get("text")))
    if direct_text:
        return direct_text

    content = item.get("content")
    if isinstance(content, str):
        return clean_text(content)
    parts = []
    for part in list_value(content):
        if isinstance(part, str):
            text = clean_text(part)
        else:
            text = clean_text(string_value(mapping_value(part).get("text")))
        if text:
            parts.append(text)
    return "\n".join(parts)


def latest_agent_text_from_items(items: Sequence[Any]) -> str:
    for item in reversed(items):
        if not is_item_type(item, "agentMessage"):
            continue
        text = clean_text(string_value(mapping_value(item).get("text")))
        if text:
            return text
    return ""


def updated_at_from_activity(thread: Mapping[str, Any], latest_turn: Mapping[str, Any]) -> str:
    for value in (
        thread.get("updatedAt"),
        latest_turn.get("completedAt"),
        latest_turn.get("startedAt"),
        thread.get("createdAt"),
    ):
        text = timestamp_to_text(value)
        if text:
            return text
    return ""


def timestamp_to_text(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(value).astimezone().isoformat()
    except (OSError, OverflowError, ValueError):
        return ""


def sentence_case(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return cleaned
    return cleaned[0].upper() + cleaned[1:]


def clean_text(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]{1,80}>", " ", text)
    return text.strip()


def contains_any(text: str, needles: Sequence[str]) -> bool:
    return any(needle in text for needle in needles)


def is_item_type(item: Any, expected: str) -> bool:
    return string_value(mapping_value(item).get("type")) == expected


def mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
