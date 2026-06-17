import unittest

from vibe_board.codex_focus import summarize_codex_focus


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
            "I am implementing the preview panel and data loader.",
        )
        self.assertNotIn("Show the user's broad Codex focus", summary.focus)
        self.assertEqual(summary.phase, "implementing changes")
        self.assertTrue(summary.available)

    def test_does_not_use_user_prompt_when_codex_has_not_posted_feedback(self) -> None:
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

        self.assertEqual(summary.focus, "No visible Codex update yet.")
        self.assertNotIn("Create a compact status summary", summary.focus)

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


if __name__ == "__main__":
    unittest.main()
