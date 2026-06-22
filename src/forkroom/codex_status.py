import json
import os
import queue
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


UNKNOWN_RUN_STATE = "unknown"
DEFAULT_CONTROL_SOCKET = Path("~/.codex/app-server-control/app-server-control.sock").expanduser()
DEFAULT_CODEX_APP_BIN = Path("/Applications/Codex.app/Contents/Resources/codex")


class CodexStatusError(Exception):
    """Raised when Codex runtime state cannot be queried."""


@dataclass(frozen=True)
class CodexRunInfo:
    thread_status: str = ""
    turn_status: str = ""
    turn_error: str = ""
    turn_completed: bool = True
    active_flags: Tuple[str, ...] = ()


def load_codex_run_states(thread_ids: Sequence[str], timeout_seconds: float = 4.0) -> Dict[str, str]:
    unique_thread_ids = dedupe_thread_ids(thread_ids)
    if not unique_thread_ids:
        return {}

    codex_bin = resolve_codex_bin()
    if not codex_bin:
        return unknown_states(unique_thread_ids)

    for command in codex_status_commands(codex_bin):
        try:
            return load_codex_run_states_with_command(command, unique_thread_ids, timeout_seconds)
        except CodexStatusError:
            continue
    return unknown_states(unique_thread_ids)


def codex_status_commands(codex_bin: str) -> List[List[str]]:
    commands: List[List[str]] = []
    proxy_socket = os.environ.get("FORKROOM_CODEX_PROXY_SOCK")
    if proxy_socket:
        commands.append([codex_bin, "app-server", "proxy", "--sock", proxy_socket])
    elif DEFAULT_CONTROL_SOCKET.exists():
        commands.append([codex_bin, "app-server", "proxy"])
    commands.append([codex_bin, "app-server"])
    return commands


def resolve_codex_bin() -> str:
    configured = os.environ.get("FORKROOM_CODEX_BIN")
    if configured:
        return configured
    discovered = shutil.which("codex")
    if discovered:
        return discovered
    if DEFAULT_CODEX_APP_BIN.is_file():
        return str(DEFAULT_CODEX_APP_BIN)
    return ""


def dedupe_thread_ids(thread_ids: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(t.strip() for t in thread_ids if t.strip()))


def unknown_states(thread_ids: Sequence[str]) -> Dict[str, str]:
    return {thread_id: UNKNOWN_RUN_STATE for thread_id in thread_ids}


def load_codex_run_states_with_command(
    command: Sequence[str],
    thread_ids: Sequence[str],
    timeout_seconds: float,
) -> Dict[str, str]:
    deadline = time.monotonic() + timeout_seconds
    client = JsonRpcProcess(command)
    try:
        client.request(
            {
                "method": "initialize",
                "id": 1,
                "params": {
                    "clientInfo": {
                        "name": "forkroom",
                        "title": "ForkRoom",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            },
            request_id=1,
            deadline=deadline,
        )
        client.notify({"method": "initialized", "params": {}})
        return read_run_states(client, thread_ids, deadline)
    finally:
        client.close()


def read_run_states(client: "JsonRpcProcess", thread_ids: Sequence[str], deadline: float) -> Dict[str, str]:
    run_info = {thread_id: CodexRunInfo() for thread_id in thread_ids}
    pending: Dict[int, Tuple[str, str]] = {}
    request_id = 2

    for thread_id in thread_ids:
        pending[request_id] = (thread_id, "thread")
        client.notify(
            {
                "method": "thread/read",
                "id": request_id,
                "params": {"threadId": thread_id, "includeTurns": False},
            }
        )
        request_id += 1
        pending[request_id] = (thread_id, "turn")
        client.notify(
            {
                "method": "thread/turns/list",
                "id": request_id,
                "params": {"threadId": thread_id, "limit": 1, "itemsView": "notLoaded"},
            }
        )
        request_id += 1

    while pending and time.monotonic() < deadline:
        message = client.next_message(deadline)
        if message is None:
            if client.is_finished():
                raise CodexStatusError(client.stderr_text() or "Codex app-server exited before responding")
            continue
        raw_id = message.get("id")
        if not isinstance(raw_id, int) or raw_id not in pending:
            continue
        thread_id, kind = pending.pop(raw_id)
        if "error" in message:
            continue
        result = message.get("result")
        if not isinstance(result, Mapping):
            continue
        current = run_info[thread_id]
        if kind == "thread":
            thread_status, active_flags = parse_thread_status(result)
            run_info[thread_id] = CodexRunInfo(
                thread_status=thread_status,
                turn_status=current.turn_status,
                turn_error=current.turn_error,
                turn_completed=current.turn_completed,
                active_flags=active_flags,
            )
        else:
            turn_status, turn_error, turn_completed = parse_latest_turn_status(result)
            run_info[thread_id] = CodexRunInfo(
                thread_status=current.thread_status,
                turn_status=turn_status,
                turn_error=turn_error,
                turn_completed=turn_completed,
                active_flags=current.active_flags,
            )

    if pending:
        raise CodexStatusError("Timed out waiting for Codex app-server run state responses")

    return {thread_id: summarize_run_state(run_info[thread_id]) for thread_id in thread_ids}


def parse_thread_status(result: Mapping[str, Any]) -> Tuple[str, Tuple[str, ...]]:
    thread = result.get("thread")
    if not isinstance(thread, Mapping):
        return "", ()
    status = thread.get("status")
    if not isinstance(status, Mapping):
        return "", ()

    status_type = status.get("type")
    raw_flags = status.get("activeFlags", [])
    flags = tuple(str(flag) for flag in raw_flags if isinstance(flag, str)) if isinstance(raw_flags, list) else ()
    return str(status_type) if status_type else "", flags


def parse_latest_turn_status(result: Mapping[str, Any]) -> Tuple[str, str, bool]:
    data = result.get("data")
    if not isinstance(data, list) or not data:
        return "", "", True
    latest = data[0]
    if not isinstance(latest, Mapping):
        return "", "", True

    status = latest.get("status")
    turn_completed = latest.get("completedAt") is not None
    error = latest.get("error")
    if isinstance(error, Mapping):
        error_message = str(error.get("message", "") or "error")
    elif error:
        error_message = str(error)
    else:
        error_message = ""
    return str(status) if status else "", error_message, turn_completed


def summarize_run_state(info: CodexRunInfo) -> str:
    if info.thread_status == "systemError":
        return "error"
    if info.turn_status == "failed" or info.turn_error:
        return "failed"
    if info.thread_status == "active":
        if "waitingOnApproval" in info.active_flags:
            return "waiting"
        return "active"
    if info.turn_status == "inProgress":
        return "active"
    if info.turn_status in {"completed", "interrupted"}:
        if not info.turn_completed:
            return "active"
        return info.turn_status
    if info.thread_status in {"idle", "notLoaded"}:
        return info.thread_status
    return UNKNOWN_RUN_STATE


class JsonRpcProcess:
    def __init__(self, command: Sequence[str]) -> None:
        try:
            self.process = subprocess.Popen(
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            raise CodexStatusError(str(exc)) from exc
        self.messages: "queue.Queue[Mapping[str, Any]]" = queue.Queue()
        self.reader = threading.Thread(target=self.read_stdout, daemon=True)
        self.reader.start()

    def read_stdout(self) -> None:
        stdout = self.process.stdout
        if stdout is None:
            return
        for line in stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(message, Mapping):
                self.messages.put(message)

    def notify(self, message: Mapping[str, Any]) -> None:
        stdin = self.process.stdin
        if stdin is None or self.process.poll() is not None:
            raise CodexStatusError(self.stderr_text() or "Codex app-server is not running")
        try:
            stdin.write(json.dumps(message) + "\n")
            stdin.flush()
        except OSError as exc:
            raise CodexStatusError(self.stderr_text() or str(exc)) from exc

    def request(self, message: Mapping[str, Any], request_id: int, deadline: float) -> Mapping[str, Any]:
        self.notify(message)
        while time.monotonic() < deadline:
            response = self.next_message(deadline)
            if response is None:
                if self.process.poll() is not None:
                    raise CodexStatusError(self.stderr_text() or "Codex app-server exited before responding")
                continue
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise CodexStatusError(str(response["error"]))
            result = response.get("result")
            return result if isinstance(result, Mapping) else {}
        raise CodexStatusError("Timed out waiting for Codex app-server response")

    def next_message(self, deadline: float) -> Optional[Mapping[str, Any]]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        try:
            return self.messages.get(timeout=min(remaining, 0.1))
        except queue.Empty:
            return None

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def is_finished(self) -> bool:
        return self.process.poll() is not None

    def stderr_text(self) -> str:
        if self.process.poll() is None:
            return ""
        stderr = self.process.stderr
        if stderr is None:
            return ""
        try:
            return stderr.read()
        except Exception:
            return ""
