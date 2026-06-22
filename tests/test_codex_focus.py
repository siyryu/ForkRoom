import unittest

from forkroom.codex_focus import summarize_codex_focus


class CodexFocusTests(unittest.TestCase):
    def test_summarizes_active_focus_from_recent_codex_feedback(self) -> None:
        summary = summarize_codex_focus(
            "thread-1",
            {
                "thread": {
                    "preview": "Build a high-level Codex session focus preview.",
                    "status": {"type": "active"},
                    "updatedAt": 1781520113,
                }
            },
            {
                "data": [
                    {
                        "status": "inProgress",
                        "completedAt": None,
                        "startedAt": 1781520112,
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [
                                    {
                                        "type": "input_text",
                                        "text": "Show the user's broad Codex focus after a session is selected.",
                                    }
                                ],
                            },
                            {
                                "type": "agentMessage",
                                "phase": "commentary",
                                "text": "I am implementing the preview panel and data loader.",
                            },
                        ],
                    }
                ]
            },
        )

        self.assertEqual(summary.state, "active")
        self.assertEqual(
            summary.focus,
            "Last command:\n"
            "Show the user's broad Codex focus after a session is selected.\n\n"
            "Codex update:\n"
            "I am implementing the preview panel and data loader.",
        )
        self.assertEqual(summary.last_user_command, "Show the user's broad Codex focus after a session is selected.")
        self.assertEqual(summary.codex_update, "I am implementing the preview panel and data loader.")
        self.assertEqual(summary.phase, "implementing changes")
        self.assertTrue(summary.available)

    def test_shows_user_command_when_codex_has_not_posted_feedback(self) -> None:
        summary = summarize_codex_focus(
            "thread-1",
            {"thread": {"preview": "Fallback preview", "status": {"type": "active"}}},
            {
                "data": [
                    {
                        "status": "inProgress",
                        "items": [{"type": "userMessage", "content": [{"text": "start"}]}],
                    },
                    {
                        "status": "completed",
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [
                                    {
                                        "text": "Create a compact status summary that explains the session's current direction."
                                    }
                                ],
                            }
                        ],
                    },
                ]
            },
        )

        self.assertEqual(
            summary.focus,
            "Last command:\n"
            "start\n\n"
            "Codex update:\n"
            "No visible Codex update yet.",
        )
        self.assertEqual(summary.last_user_command, "start")
        self.assertEqual(summary.codex_update, "No visible Codex update yet.")

    def test_waiting_for_approval_overrides_phase(self) -> None:
        summary = summarize_codex_focus(
            "thread-1",
            {"thread": {"preview": "Approval flow", "status": {"type": "active", "activeFlags": ["waitingOnApproval"]}}},
            {"data": [{"status": "inProgress", "items": []}]},
        )

        self.assertEqual(summary.state, "waiting")
        self.assertEqual(summary.phase, "waiting for user approval")

    def test_command_details_are_not_exposed_in_command_only_activity(self) -> None:
        summary = summarize_codex_focus(
            "thread-1",
            {
                "thread": {
                    "preview": "Verify the session focus preview.",
                    "status": {"type": "active"},
                }
            },
            {
                "data": [
                    {
                        "status": "inProgress",
                        "items": [
                            {
                                "type": "commandExecution",
                                "command": "pytest tests/test_app_sessions.py --secret-token example",
                            }
                        ],
                    }
                ]
            },
        )

        rendered = "\n".join((summary.focus, summary.phase))
        self.assertEqual(summary.focus, "Working through implementation details.")
        self.assertEqual(summary.phase, "working through implementation details")
        self.assertNotIn("pytest", rendered)
        self.assertNotIn("secret-token", rendered)

    def test_reads_user_command_without_exposing_tool_command_details(self) -> None:
        summary = summarize_codex_focus(
            "thread-1",
            {"thread": {"preview": "Run tests", "status": {"type": "active"}}},
            {
                "data": [
                    {
                        "status": "inProgress",
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [{"type": "input_text", "text": "Run the focused tests."}],
                            },
                            {
                                "type": "commandExecution",
                                "command": "pytest tests/test_codex_focus.py --secret-token example",
                            },
                        ],
                    }
                ]
            },
        )

        self.assertEqual(
            summary.focus,
            "Last command:\n"
            "Run the focused tests.\n\n"
            "Codex update:\n"
            "Working through implementation details.",
        )
        self.assertNotIn("pytest", summary.focus)
        self.assertNotIn("secret-token", summary.focus)

    def test_preview_keeps_full_text_for_ui_to_fit_by_height(self) -> None:
        long_first_line = "Keep this long line intact: " + ("x" * 120)
        user_prompt = "\n".join(
            [
                long_first_line,
                "Prompt line 2",
                "Prompt line 3",
                "Prompt line 4",
                "Prompt line 5",
            ]
        )
        codex_update = "\n".join("Codex line {0}".format(index) for index in range(1, 18))

        summary = summarize_codex_focus(
            "thread-1",
            {"thread": {"preview": "Long preview", "status": {"type": "active"}}},
            {
                "data": [
                    {
                        "status": "inProgress",
                        "items": [
                            {
                                "type": "userMessage",
                                "content": [{"type": "input_text", "text": user_prompt}],
                            },
                            {
                                "type": "agentMessage",
                                "phase": "commentary",
                                "text": codex_update,
                            },
                        ],
                    }
                ]
            },
        )

        self.assertEqual(
            summary.last_user_command.splitlines(),
            [long_first_line, "Prompt line 2", "Prompt line 3", "Prompt line 4", "Prompt line 5"],
        )
        self.assertEqual(len(summary.codex_update.splitlines()), 17)
        self.assertEqual(summary.codex_update.splitlines()[-1], "Codex line 17")
        self.assertIn(long_first_line, summary.focus)
        self.assertIn("Prompt line 5", summary.last_user_command)
        self.assertIn("Codex line 17", summary.codex_update)


if __name__ == "__main__":
    unittest.main()
