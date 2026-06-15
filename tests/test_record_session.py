import json
import tempfile
import unittest
from pathlib import Path

from scripts.record_session import RecordSessionError, codex_thread_deeplink, record_session


class RecordSessionTest(unittest.TestCase):
    def test_records_full_session_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = self.write_manifest(root, "alpha", {"id": "alpha", "updated_at": "old"})

            record_session(
                root=root,
                exp_id="alpha",
                thread_id="thread with spaces",
                title="Initial implementation",
                status="running",
                created_at="2026-06-15T10:00:00+08:00",
                updated_at="2026-06-15T10:30:00+08:00",
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["updated_at"], "2026-06-15T10:30:00+08:00")
            self.assertEqual(
                manifest["sessions"],
                [
                    {
                        "id": "thread with spaces",
                        "title": "Initial implementation",
                        "agent": "codex",
                        "status": "running",
                        "created_at": "2026-06-15T10:00:00+08:00",
                        "updated_at": "2026-06-15T10:30:00+08:00",
                        "deeplink": "codex://threads/thread%20with%20spaces",
                    }
                ],
            )

    def test_updates_existing_session_without_changing_created_at(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = self.write_manifest(
                root,
                "alpha",
                {
                    "id": "alpha",
                    "sessions": [
                        {
                            "id": "thread-1",
                            "title": "Old title",
                            "agent": "codex",
                            "status": "running",
                            "created_at": "2026-06-15T10:00:00+08:00",
                            "updated_at": "2026-06-15T10:05:00+08:00",
                            "deeplink": "codex://threads/thread-1",
                            "metadata": {"kept": True},
                        }
                    ],
                },
            )

            record_session(
                root=root,
                exp_id="alpha",
                thread_id="thread-1",
                title="New title",
                status="ready",
                created_at="2026-06-15T11:00:00+08:00",
                updated_at="2026-06-15T11:10:00+08:00",
            )

            session = json.loads(manifest_path.read_text(encoding="utf-8"))["sessions"][0]
            self.assertEqual(session["title"], "New title")
            self.assertEqual(session["status"], "ready")
            self.assertEqual(session["created_at"], "2026-06-15T10:00:00+08:00")
            self.assertEqual(session["updated_at"], "2026-06-15T11:10:00+08:00")
            self.assertEqual(session["metadata"], {"kept": True})

    def test_converts_matching_string_session_to_object(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = self.write_manifest(root, "alpha", {"id": "alpha", "sessions": ["thread-1"]})

            record_session(
                root=root,
                exp_id="alpha",
                thread_id="thread-1",
                title="Thread one",
                created_at="2026-06-15T10:00:00+08:00",
                updated_at="2026-06-15T10:00:00+08:00",
            )

            session = json.loads(manifest_path.read_text(encoding="utf-8"))["sessions"][0]
            self.assertEqual(session["id"], "thread-1")
            self.assertEqual(session["title"], "Thread one")

    def test_deduplicates_matching_sessions_in_current_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest_path = self.write_manifest(
                root,
                "alpha",
                {
                    "id": "alpha",
                    "sessions": [
                        {"id": "thread-1", "title": "Old title"},
                        {"id": "thread-2", "title": "Other title"},
                        "thread-1",
                    ],
                },
            )

            record_session(
                root=root,
                exp_id="alpha",
                thread_id="thread-1",
                title="New title",
                created_at="2026-06-15T10:00:00+08:00",
                updated_at="2026-06-15T10:00:00+08:00",
            )

            sessions = json.loads(manifest_path.read_text(encoding="utf-8"))["sessions"]
            self.assertEqual([session["id"] if isinstance(session, dict) else session for session in sessions], ["thread-1", "thread-2"])
            self.assertEqual(sessions[0]["title"], "New title")

    def test_rejects_session_already_owned_by_another_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_manifest(root, "alpha", {"id": "alpha", "sessions": [{"id": "thread-1"}]})
            self.write_manifest(root, "beta", {"id": "beta"})

            with self.assertRaises(RecordSessionError):
                record_session(root=root, exp_id="beta", thread_id="thread-1")

    def test_rejects_non_list_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_manifest(root, "alpha", {"id": "alpha", "sessions": {"id": "thread-1"}})

            with self.assertRaises(RecordSessionError):
                record_session(root=root, exp_id="alpha", thread_id="thread-1")

    def test_codex_thread_deeplink_escapes_thread_ids(self) -> None:
        self.assertEqual(codex_thread_deeplink("thread with spaces"), "codex://threads/thread%20with%20spaces")

    def write_manifest(self, root: Path, exp_id: str, manifest: dict) -> Path:
        exp_path = root / ".agents" / "exps" / exp_id
        exp_path.mkdir(parents=True)
        manifest_path = exp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path


if __name__ == "__main__":
    unittest.main()
