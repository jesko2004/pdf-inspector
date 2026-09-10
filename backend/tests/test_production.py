import json
import sqlite3
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.backup import create_backup, restore_backup, verify_backup
from backend.config import Settings
from backend.service import CapacityExceededError, TaskService
from backend.task_store import TaskStore

BUILTIN_PROFILES = Path(__file__).resolve().parents[1] / "profiles"


def processor(_pdf_path, profile):
    return {
        "profile_id": profile.id,
        "profile_version": profile.version,
        "status": "ready",
        "fields": {},
        "issues": [],
        "document": {"page_count": 1, "pages_needing_ocr": []},
        "tables": {"status": "ready", "items": [], "issues": []},
        "chunks": [],
        "markdown": "test",
    }


class ProductionControlsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.settings = Settings(
            data_dir=Path(self.temporary.name),
            builtin_profile_dir=BUILTIN_PROFILES,
            worker_count=1,
            api_keys=(
                ("reader", "read-secret", "read"),
                ("writer", "write-secret", "write"),
                ("operator", "admin-secret", "admin"),
            ),
            search_rate_limit_per_minute=1,
        )
        self.app = create_app(self.settings, processor=processor, start_workers=False)
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def headers(self, secret):
        return {"Authorization": f"Bearer {secret}"}

    def test_auth_roles_request_ids_and_audit(self):
        self.assertEqual(200, self.client.get("/health").status_code)
        self.assertEqual(401, self.client.get("/v1/tasks").status_code)
        self.assertEqual(
            200,
            self.client.get(
                "/v1/tasks", headers=self.headers("read-secret")
            ).status_code,
        )
        denied = self.client.post(
            "/v1/tasks",
            headers=self.headers("read-secret"),
            files={"file": ("a.pdf", b"%PDF-1.7", "application/pdf")},
        )
        self.assertEqual(403, denied.status_code)
        created = self.client.post(
            "/v1/tasks",
            headers={**self.headers("write-secret"), "X-Request-ID": "trace-123"},
            files={"file": ("a.pdf", b"%PDF-1.7", "application/pdf")},
        )
        self.assertEqual(202, created.status_code)
        self.assertEqual("trace-123", created.headers["x-request-id"])
        self.assertEqual(
            403,
            self.client.get(
                "/v1/audit-events", headers=self.headers("write-secret")
            ).status_code,
        )
        events = self.client.get(
            "/v1/audit-events", headers=self.headers("admin-secret")
        ).json()["items"]
        self.assertTrue(any(event["request_id"] == "trace-123" for event in events))
        self.assertFalse(any("secret" in json.dumps(event) for event in events))

    def test_metrics_and_rate_limit(self):
        forbidden = self.client.get("/metrics", headers=self.headers("read-secret"))
        self.assertEqual(403, forbidden.status_code)
        metrics = self.client.get("/metrics", headers=self.headers("admin-secret"))
        self.assertEqual(200, metrics.status_code)
        self.assertIn("pdf_inspector_http_requests_total", metrics.text)

        created = self.client.post(
            "/v1/knowledge-bases",
            headers=self.headers("write-secret"),
            json={"name": "kb"},
        ).json()
        url = f"/v1/knowledge-bases/{created['id']}/search"
        first = self.client.post(
            url,
            headers=self.headers("read-secret"),
            json={"query": "hello", "min_score": -1},
        )
        self.assertEqual(200, first.status_code)
        limited = self.client.post(
            url,
            headers=self.headers("read-secret"),
            json={"query": "hello", "min_score": -1},
        )
        self.assertEqual(429, limited.status_code)
        self.assertIn("retry-after", limited.headers)

    def test_rag_token_limits_return_explicit_errors(self):
        too_much_context = self.client.post(
            "/v1/knowledge-bases/missing/ask",
            headers=self.headers("read-secret"),
            json={"question": "hello", "max_context_tokens": 4001},
        )
        self.assertEqual(422, too_much_context.status_code)
        self.assertEqual(
            "context_token_limit_exceeded",
            too_much_context.json()["detail"]["code"],
        )
        too_much_output = self.client.post(
            "/v1/knowledge-bases/missing/ask",
            headers=self.headers("read-secret"),
            json={"question": "hello", "max_output_tokens": 801},
        )
        self.assertEqual(422, too_much_output.status_code)
        self.assertEqual(
            "output_token_limit_exceeded",
            too_much_output.json()["detail"]["code"],
        )


class CapacityAndMigrationTests(unittest.TestCase):
    def test_active_task_limit_and_schema_versions(self):
        with TemporaryDirectory() as temporary:
            settings = Settings(
                data_dir=Path(temporary),
                builtin_profile_dir=BUILTIN_PROFILES,
                worker_count=1,
                max_active_tasks=1,
            )
            service = TaskService(settings, processor=processor, start_workers=False)
            try:
                service.create_task("one.pdf", BytesIO(b"%PDF-1.7"), "purchase_quote")
                with self.assertRaises(CapacityExceededError):
                    service.create_task(
                        "two.pdf", BytesIO(b"%PDF-1.7"), "purchase_quote"
                    )
                connection = sqlite3.connect(settings.database_path)
                try:
                    version = connection.execute(
                        "SELECT version FROM schema_migrations WHERE component='tasks'"
                    ).fetchone()
                finally:
                    connection.close()
                self.assertEqual((1,), version)
            finally:
                service.close()

    def test_existing_unversioned_database_is_adopted_without_data_loss(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "tasks.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    CREATE TABLE tasks (
                        id TEXT PRIMARY KEY, filename TEXT NOT NULL,
                        profile_id TEXT NOT NULL, profile_version INTEGER NOT NULL,
                        profile_json TEXT NOT NULL, status TEXT NOT NULL,
                        attempts INTEGER NOT NULL DEFAULT 0, pdf_path TEXT NOT NULL,
                        result_path TEXT, error_code TEXT, error_message TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO tasks(
                        id, filename, profile_id, profile_version, profile_json,
                        status, attempts, pdf_path, created_at, updated_at
                    ) VALUES ('legacy', 'old.pdf', 'purchase_quote', 1, '{}',
                              'ready', 1, 'old.pdf', 'before', 'before')
                    """
                )
                connection.commit()
            finally:
                connection.close()

            store = TaskStore(database)
            self.assertEqual("old.pdf", store.get("legacy")["filename"])
            connection = sqlite3.connect(database)
            try:
                migrated = connection.execute(
                    "SELECT version, name FROM schema_migrations WHERE component='tasks'"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual((1, "baseline_task_schema"), migrated)


class BackupTests(unittest.TestCase):
    def test_backup_verify_and_restore(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "source"
            data_dir.mkdir()
            connection = sqlite3.connect(data_dir / "tasks.sqlite3")
            try:
                connection.execute("CREATE TABLE test(value TEXT)")
                connection.execute("INSERT INTO test VALUES ('ok')")
                connection.commit()
            finally:
                connection.close()
            upload = data_dir / "uploads" / "one.pdf"
            upload.parent.mkdir()
            upload.write_bytes(b"%PDF-1.7")
            archive = root / "backup.tar.gz"
            manifest = create_backup(data_dir, archive)
            self.assertEqual(2, len(manifest["files"]))
            self.assertEqual(manifest, verify_backup(archive))

            restored = root / "restored"
            restore_backup(archive, restored)
            self.assertEqual(
                b"%PDF-1.7", (restored / "uploads" / "one.pdf").read_bytes()
            )
            connection = sqlite3.connect(restored / "tasks.sqlite3")
            try:
                value = connection.execute("SELECT value FROM test").fetchone()
            finally:
                connection.close()
            self.assertEqual(("ok",), value)
            with self.assertRaises(FileExistsError):
                restore_backup(archive, restored)


if __name__ == "__main__":
    unittest.main()
