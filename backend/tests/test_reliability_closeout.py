"""Fault-driven single-machine release checks; no external paid providers."""
import json
import os
import subprocess
import signal
import sqlite3
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.backup import create_backup, restore_backup
from backend.config import Settings
from backend.execution_lock import SingleExecutorLock
from backend.index_lifecycle import drain_deletions, queue_deletions
from backend.knowledge_store import KnowledgeStore
from backend.maintenance import deletion_status, reset_deletions
from backend.observability import SlidingWindowRateLimiter
from backend.operations import OperationConflictError, OperationStore, fingerprint
from backend.process_isolation import ProcessingTimeoutError
from backend.reranking import IsolatedReranker
from backend.resource_lifecycle import cleanup_owned_files
from backend.tests.test_api import BUILTIN_PROFILES, processor
from backend.tests import test_index_publication as publications
from backend.tests.test_process_isolation import process_running, wait_for_file


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = OperationStore(self.root / "tasks.sqlite3")

    def tearDown(self):
        self.temporary.cleanup()

    def test_completed_paid_result_survives_restart_without_another_call(self):
        calls = []
        callback = lambda _: calls.append(1) or {"answer": "saved", "citations": ["old-version"]}
        first = self.store.execute("alice", "ask:kb", "request-1", fingerprint({"question": "q"}), callback)
        second = OperationStore(self.store.database_path, recover_incomplete=True).execute(
            "alice", "ask:kb", "request-1", fingerprint({"question": "q"}), callback)
        self.assertEqual(first[:2], second[:2])
        self.assertTrue(second[2])
        self.assertEqual([1], calls)
        with self.assertRaises(KeyError):
            self.store.get(first[1], "bob")
        with self.assertRaises(OperationConflictError):
            self.store.execute("alice", "ask:kb", "request-1", "changed", callback)

    def test_concurrent_retry_cannot_start_second_paid_call(self):
        entered, release = Event(), Event()
        def slow(_):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"answer": "saved"}
        with ThreadPoolExecutor(1) as executor:
            future = executor.submit(self.store.execute, "a", "ask:kb", "one", "fp", slow)
            self.assertTrue(entered.wait(5))
            try:
                with self.assertRaisesRegex(OperationConflictError, "operation_processing"):
                    self.store.execute("a", "ask:kb", "one", "fp", lambda _: self.fail("duplicate provider call"))
            finally:
                release.set()
            future.result(5)

    def test_provider_timeout_and_lost_checkpoint_never_auto_recall(self):
        calls = []
        def timeout(_):
            calls.append(1)
            raise TimeoutError("possibly charged")
        with self.assertRaises(TimeoutError):
            self.store.execute("a", "ask:kb", "timeout", "fp", timeout)
        with self.assertRaises(OperationConflictError):
            self.store.execute("a", "ask:kb", "timeout", "fp", timeout)
        self.assertEqual([1], calls)
        with patch.object(self.store, "complete", side_effect=RuntimeError("lost checkpoint")):
            with self.assertRaises(RuntimeError):
                self.store.execute("a", "ask:kb", "lost", "fp", lambda _: {"answer": "already generated"})
        restarted = OperationStore(self.store.database_path, recover_incomplete=True)
        with self.assertRaises(OperationConflictError):
            restarted.execute("a", "ask:kb", "lost", "fp", lambda _: self.fail("charged again"))

    def test_abrupt_incomplete_and_upload_checkpoint_recovery(self):
        with patch.object(self.store, "complete", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.store.execute("a", "upload", "upload", "fp", lambda op: {"id": op})
        recovered = self.store.execute("a", "upload", "upload", "fp", lambda _: self.fail("second upload"), recover=lambda op: {"id": op})
        self.assertTrue(recovered[2])
        with self.store._connect() as connection:
            connection.execute("UPDATE request_operations SET status='processing' WHERE id=?", (recovered[1],))
        restarted = OperationStore(self.store.database_path, recover_incomplete=True)
        self.assertEqual("uncertain", restarted.get(recovered[1], "a")["status"])

    def test_http_upload_replay_conflict_and_paid_stream_replay(self):
        app = create_app(Settings(self.root, BUILTIN_PROFILES, max_active_tasks=1), processor=processor, start_workers=False)
        with TestClient(app) as client:
            options = {"files": {"file": ("one.pdf", b"%PDF-1.7")}, "headers": {"Idempotency-Key": "upload-1"}}
            first = client.post("/v1/tasks", **options)
            second = client.post("/v1/tasks", **options)
            self.assertEqual(202, first.status_code)
            self.assertEqual(first.json(), second.json())
            self.assertEqual("true", second.headers["Idempotency-Replayed"])
            conflict = client.post("/v1/tasks", files={"file": ("other.pdf", b"%PDF-1.7other")}, headers=options["headers"])
            self.assertEqual(409, conflict.status_code)
            self.assertEqual(1, len(app.state.service.list_tasks()))
            result = {"answer_id": str(uuid4()), "answer": "completed", "citations": [], "refused": False,
                      "generation_latency_ms": 0, "usage": {}}
            with patch.object(app.state.rag, "prepare"), patch.object(app.state.rag, "answer", return_value=result) as call, patch.object(app.state.knowledge.store, "record_answer"):
                path = "/v1/knowledge-bases/kb/ask"
                args = {"json": {"question": "q", "stream": True}, "headers": {"Idempotency-Key": "ask-1"}}
                one, two = client.post(path, **args), client.post(path, **args)
                self.assertEqual(200, one.status_code)
                self.assertEqual(one.text, two.text)
                self.assertIn("event: done", two.text)
                self.assertEqual(1, call.call_count)
                self.assertEqual("completed", client.get("/v1/operations/" + one.headers["X-Operation-ID"]).json()["status"])


class MaintenanceAndResourcesTests(unittest.TestCase):
    def test_background_maintenance_recovers_without_new_requests(self):
        with TemporaryDirectory() as temporary:
            app = create_app(Settings(Path(temporary), BUILTIN_PROFILES), processor=processor)
            with TestClient(app):
                with app.state.knowledge.store._connect() as connection:
                    queue_deletions(connection, "gone", ["orphan"])
                deadline = time.monotonic() + 8
                while deletion_status(app.state.knowledge.store)["pending"] and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertEqual(0, deletion_status(app.state.knowledge.store)["pending"])

    def test_abrupt_executor_death_stops_native_worker_and_descendant(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = {"case": "descendant", "pid_file": str(root / "worker.pid"), "child_pid_file": str(root / "child.pid")}
            script = "from pathlib import Path; import json,sys; from backend.process_isolation import ProcessRunner; r=ProcessRunner(workers=1,memory_mb=128,max_result_bytes=4096,temporary_dir=Path(sys.argv[1]),worker_command=(sys.executable,'-m','backend.tests.isolation_fixture')); r.run(json.loads(sys.argv[2]),timeout_seconds=30)"
            owner = subprocess.Popen([sys.executable, "-c", script, str(root / "work"), json.dumps(payload)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                start_new_session=os.name != "nt")
            pids = []
            try:
                pids = [wait_for_file(root / "worker.pid"), wait_for_file(root / "child.pid")]
                owner.kill()
                owner.wait(5)
                deadline = time.monotonic() + 3
                while any(process_running(pid) for pid in pids) and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertFalse(any(process_running(pid) for pid in pids))
                self.assertTrue(any((root / "work").iterdir()))  # Crash leftovers are real.
                lock = SingleExecutorLock(root / "executor.lock")
                try:
                    cleanup_owned_files(root)
                finally:
                    lock.close()
                self.assertEqual([], list((root / "work").iterdir()))
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.wait(5)
                for pid in pids:
                    if process_running(pid):
                        os.kill(pid, signal.SIGTERM if os.name == "nt" else signal.SIGKILL)

    def test_backoff_limit_persistence_manual_reset_and_permission_stop(self):
        with TemporaryDirectory() as temporary:
            store = KnowledgeStore(Path(temporary) / "knowledge.sqlite3")
            with store._connect() as connection:
                queue_deletions(connection, "deleted-kb", ["orphan"])
            calls = []
            def fail(_connection, _ids):
                calls.append(1)
                raise RuntimeError("credentials must never be persisted")
            for _ in range(5):
                with self.assertRaises(RuntimeError):
                    drain_deletions(store, fail, scheduled=True)
                self.assertEqual(0, drain_deletions(store, fail, scheduled=True))
                with store._connect() as connection:
                    connection.execute("UPDATE vector_deletions SET next_attempt_at=0")
            restarted = KnowledgeStore(store.database_path)
            self.assertEqual(1, deletion_status(restarted)["blocked"])
            self.assertEqual(0, drain_deletions(restarted, fail, scheduled=True))
            self.assertEqual(5, len(calls))
            self.assertNotIn("credentials", json.dumps(deletion_status(restarted)))
            reset_deletions(restarted)
            with self.assertRaises(PermissionError):
                drain_deletions(restarted, lambda *_: (_ for _ in ()).throw(PermissionError("secret")), scheduled=True)
            self.assertEqual(1, deletion_status(restarted)["blocked"])
            reset_deletions(restarted)
            self.assertEqual(1, drain_deletions(restarted, lambda *_: None, scheduled=True))
            self.assertEqual(0, deletion_status(restarted)["pending"])

    def test_cleanup_preserves_committed_uploads_and_unowned_files(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = create_app(Settings(root, BUILTIN_PROFILES), processor=processor, start_workers=False)
            with TestClient(app) as client:
                task = client.post("/v1/tasks", files={"file": ("one.pdf", b"%PDF-1.7")}).json()
            stale = root / "uploads" / (str(uuid4()) + ".upload")
            stale.write_bytes(b"partial")
            user_file = root / "uploads" / "my-file.pdf"
            user_file.write_bytes(b"keep")
            work = root / "work" / "worker-crashed"
            work.mkdir(parents=True)
            (work / "output").write_text("partial")
            lock = SingleExecutorLock(root / "executor.lock")
            try:
                self.assertEqual(2, cleanup_owned_files(root))
            finally:
                lock.close()
            self.assertTrue((root / "uploads" / (task["id"] + ".pdf")).exists())
            self.assertTrue(user_file.exists())
            self.assertFalse(stale.exists())

    def test_identity_churn_cannot_grow_or_evict_active_rate_limits(self):
        limiter = SlidingWindowRateLimiter(max_identities=2)
        self.assertTrue(limiter.allow("a", "ask", 1)[0])
        self.assertTrue(limiter.allow("b", "ask", 1)[0])
        self.assertFalse(limiter.allow("c", "ask", 1)[0])
        self.assertFalse(limiter.allow("a", "ask", 1)[0])

    def test_isolated_rerank_timeout_kills_and_recovers_slot(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            worker = root / "rerank_worker.py"
            worker.write_text("""import json,os,sys
from pathlib import Path
request, output = map(Path, sys.argv[1:3])
if sys.stdin.buffer.read(1) != b'1': sys.exit()
p=json.loads(request.read_text())
if p['query']=='hang':
    Path(p['cache_dir']).parent.mkdir(parents=True, exist_ok=True)
    Path(p['cache_dir']).parent.joinpath('worker.pid').write_text(str(os.getpid()))
    while True: pass
output.write_text(json.dumps({'ok':True,'data':[[p['candidates'][0]['chunk_id'],1.0]]}))
""", encoding="utf-8")
            reranker = IsolatedReranker(Settings(root, BUILTIN_PROFILES, rerank_timeout_ms=1500), worker_command=(sys.executable, str(worker)))
            try:
                with self.assertRaises(ProcessingTimeoutError):
                    reranker.rerank("hang", [{"chunk_id": "one", "content": "text"}], 1)
                pid = wait_for_file(reranker.settings.rerank_cache_dir.parent / "worker.pid")
                deadline = time.monotonic() + 3
                while process_running(pid) and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertFalse(process_running(pid))
                self.assertEqual([("one", 1.0)], reranker.rerank("ok", [{"chunk_id": "one", "content": "text"}], 1))
            finally:
                reranker.close()

    def test_active_service_excludes_backup_and_corrupt_restore_is_not_published(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / "data"
            data.mkdir()
            lock = SingleExecutorLock(data / "executor.lock")
            try:
                with self.assertRaises(RuntimeError):
                    create_backup(data, root / "busy.tar.gz")
                self.assertFalse((root / "busy.tar.gz").exists())
            finally:
                lock.close()
            with self.assertRaises(ValueError):
                create_backup(data, data / "inside.tar.gz")
            with self.assertRaises(ValueError):
                create_backup(data, root / "external.tar.gz", vector_store="pgvector")
            (data / "bad.sqlite3").write_bytes(b"corrupt SQLite")
            with self.assertRaises(sqlite3.DatabaseError):
                create_backup(data, root / "corrupt.tar.gz")
            self.assertFalse((root / "corrupt.tar.gz").exists())

    def test_failed_app_initialization_releases_executor_ownership(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = Settings(root, BUILTIN_PROFILES)
            with patch("backend.app.AuditStore", side_effect=RuntimeError("injected init failure")):
                with self.assertRaises(RuntimeError):
                    create_app(settings, processor=processor)
            lock = SingleExecutorLock(root / "executor.lock")
            lock.close()


class RestoredIndexTests(unittest.TestCase):
    def test_new_directory_restores_query_citations_and_index_updates(self):
        from backend.tests.test_knowledge_service import chunk
        def parse(path, profile):
            return {**processor(path, profile), "chunks": [chunk(path.name)], "status": "ready"}
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "restored"
            settings = Settings(source, BUILTIN_PROFILES, embedding_dimensions=16)
            app = create_app(settings, processor=parse, start_workers=False)
            search = dict(top_k=5, min_score=-1, document_ids=[], page_start=None, page_end=None,
                          kinds=[], section_path_prefix=[])
            with TestClient(app) as client:
                task = client.post("/v1/tasks", files={"file": ("one.pdf", b"%PDF-1.7")}, headers={"Idempotency-Key": "stable-upload"}).json()
                app.state.service.run_pending(task["id"])
                kb = client.post("/v1/knowledge-bases", json={"name": "restorable"}).json()["id"]
                app.state.knowledge.ingest_task(kb, task["id"], "manual")
                app.state.knowledge.run_pending()
                expected = app.state.knowledge.search(kb, "knowledge", **search)["items"]
                self.assertTrue(expected)
                old = app.state.knowledge.list_index_generations(kb)["active_generation_id"]
                with app.state.knowledge.store._connect() as connection:
                    connection.execute("INSERT INTO retrieval_leases VALUES (?, ?, ?, ?)",
                        (str(uuid4()), kb, json.dumps([item["chunk_id"] for item in expected]), "2026-10-05T00:00:00+00:00"))
            archive = root / "backup.tar.gz"
            create_backup(source, archive)
            source.rename(root / "source-unavailable")
            restore_backup(archive, target)
            app = create_app(replace(settings, data_dir=target), processor=parse, start_workers=False)
            with TestClient(app) as client:
                self.assertFalse(source.exists())
                with app.state.knowledge.store._connect() as connection:
                    self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM retrieval_leases").fetchone()[0])
                self.assertEqual(expected, app.state.knowledge.search(kb, "knowledge", **search)["items"])
                self.assertEqual(b"%PDF-1.7", client.get(f"/v1/tasks/{task['id']}/source").content)
                replay = client.post("/v1/tasks", files={"file": ("one.pdf", b"%PDF-1.7")}, headers={"Idempotency-Key": "stable-upload"})
                self.assertEqual(task["id"], replay.json()["id"])
                next_task = client.post("/v1/tasks", files={"file": ("two.pdf", b"%PDF-1.7-two")}).json()
                app.state.service.run_pending(next_task["id"])
                app.state.knowledge.ingest_task(kb, next_task["id"], "second")
                app.state.knowledge.run_pending()
                self.assertEqual(2, len(app.state.knowledge.search(kb, "knowledge", **search)["items"]))
                app.state.knowledge.reindex_knowledge_base(kb, embedding_provider=None, embedding_model="hash-v2", embedding_dimensions=24)
                app.state.knowledge.run_pending()
                current = app.state.knowledge.list_index_generations(kb)["active_generation_id"]
                app.state.knowledge.rollback_index(kb, generation_id=old, expected_generation_id=current, reason="restore check")
                self.assertEqual("hash-v1", app.state.knowledge.search(kb, "knowledge", **search)["embedding_model"])
