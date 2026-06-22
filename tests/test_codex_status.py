import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from forkroom.codex_status import (
    CodexStatusError,
    CodexRunInfo,
    codex_status_commands,
    dedupe_thread_ids,
    load_codex_run_states,
    parse_latest_turn_status,
    parse_thread_status,
    read_run_states,
    summarize_run_state,
)


class CodexStatusTests(unittest.TestCase):
    def test_summarizes_turn_status_before_thread_load_status(self) -> None:
        self.assertEqual(summarize_run_state(CodexRunInfo(thread_status="notLoaded", turn_status="completed")), "completed")
        self.assertEqual(summarize_run_state(CodexRunInfo(thread_status="notLoaded", turn_status="failed")), "failed")
        self.assertEqual(summarize_run_state(CodexRunInfo(thread_status="notLoaded", turn_status="inProgress")), "active")
        self.assertEqual(
            summarize_run_state(
                CodexRunInfo(thread_status="notLoaded", turn_status="interrupted", turn_completed=False)
            ),
            "active",
        )
        self.assertEqual(summarize_run_state(CodexRunInfo(thread_status="active", active_flags=("waitingOnApproval",))), "waiting")
        self.assertEqual(summarize_run_state(CodexRunInfo(thread_status="systemError")), "error")

    def test_parses_app_server_thread_and_turn_payloads(self) -> None:
        thread_status, flags = parse_thread_status(
            {
                "thread": {
                    "status": {
                        "type": "active",
                        "activeFlags": ["waitingOnApproval"],
                    }
                }
            }
        )
        turn_status, turn_error, turn_completed = parse_latest_turn_status(
            {
                "data": [
                    {
                        "status": "failed",
                        "error": {"message": "boom"},
                        "completedAt": 1781520113,
                    }
                ]
            }
        )

        self.assertEqual(thread_status, "active")
        self.assertEqual(flags, ("waitingOnApproval",))
        self.assertEqual(turn_status, "failed")
        self.assertEqual(turn_error, "boom")
        self.assertTrue(turn_completed)

    def test_parses_uncompleted_interrupted_turn_as_active(self) -> None:
        turn_status, turn_error, turn_completed = parse_latest_turn_status(
            {
                "data": [
                    {
                        "status": "interrupted",
                        "error": None,
                        "completedAt": None,
                    }
                ]
            }
        )

        self.assertEqual(turn_status, "interrupted")
        self.assertEqual(turn_error, "")
        self.assertFalse(turn_completed)

    def test_dedupes_thread_ids_without_reordering(self) -> None:
        self.assertEqual(dedupe_thread_ids([" one ", "", "two", "one"]), ["one", "two"])

    def test_skips_proxy_when_default_socket_is_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch("forkroom.codex_status.DEFAULT_CONTROL_SOCKET") as socket:
            socket.exists.return_value = False

            self.assertEqual(codex_status_commands("codex"), [["codex", "app-server"]])

    def test_uses_explicit_proxy_socket_before_fallback(self) -> None:
        with patch.dict("os.environ", {"FORKROOM_CODEX_PROXY_SOCK": "/tmp/codex.sock"}, clear=True):
            self.assertEqual(
                codex_status_commands("codex"),
                [
                    ["codex", "app-server", "proxy", "--sock", "/tmp/codex.sock"],
                    ["codex", "app-server"],
                ],
            )

    def test_load_states_uses_macos_app_bundle_when_codex_is_not_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex_bin = Path(tmp) / "Codex.app" / "Contents" / "Resources" / "codex"
            codex_bin.parent.mkdir(parents=True)
            codex_bin.write_text("", encoding="utf-8")

            with (
                patch.dict("os.environ", {}, clear=True),
                patch("forkroom.codex_status.shutil.which", return_value=None),
                patch("forkroom.codex_status.DEFAULT_CODEX_APP_BIN", codex_bin),
                patch("forkroom.codex_status.DEFAULT_CONTROL_SOCKET") as socket,
                patch("forkroom.codex_status.load_codex_run_states_with_command") as load_with_command,
            ):
                socket.exists.return_value = False
                load_with_command.return_value = {"thread-1": "active"}

                self.assertEqual(load_codex_run_states(["thread-1"]), {"thread-1": "active"})

            load_with_command.assert_called_once()
            self.assertEqual(load_with_command.call_args.args[0][0], str(codex_bin))

    def test_incomplete_app_server_query_is_not_reported_as_unknown(self) -> None:
        class UnresponsiveClient:
            def notify(self, message: object) -> None:
                pass

            def next_message(self, deadline: float) -> object:
                return None

            def is_finished(self) -> bool:
                return False

            def stderr_text(self) -> str:
                return ""

        with self.assertRaises(CodexStatusError):
            read_run_states(UnresponsiveClient(), ["thread-1"], time.monotonic() + 0.01)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
