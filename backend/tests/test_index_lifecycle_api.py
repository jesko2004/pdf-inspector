import unittest
from unittest.mock import patch

from backend.tests import test_production as production


class IndexLifecycleApiTests(unittest.TestCase):
    setUp = production.ProductionControlsTests.setUp
    tearDown = production.ProductionControlsTests.tearDown
    headers = production.ProductionControlsTests.headers

    def urls(self):
        response = self.client.post("/v1/knowledge-bases", headers=self.headers("write-secret"), json={"name": "index-lifecycle"})
        self.assertEqual(201, response.status_code)
        base = "/v1/knowledge-bases/" + response.json()["id"]
        summary = self.client.get(base + "/index-generations", headers=self.headers("read-secret"))
        self.assertEqual(200, summary.status_code)
        return base, summary.json()["active_generation_id"]

    def test_reader_can_inspect_but_only_admin_can_preview_gc_or_rollback(self):
        base, current = self.urls()
        for suffix, payload in (("/index-garbage-collection", {}),
                                ("/index-generations/rollback", {"generation_id": current, "expected_generation_id": current, "reason": "review"})):
            for secret in ("read-secret", "write-secret"):
                self.assertEqual(403, self.client.post(base + suffix, headers=self.headers(secret), json=payload).status_code)
            self.assertEqual(200, self.client.post(base + suffix, headers=self.headers("admin-secret"), json=payload).status_code)
        events = self.client.get("/v1/audit-events", headers=self.headers("admin-secret")).json()["items"]
        self.assertTrue(any(e["path"].endswith("/index-garbage-collection") for e in events))

    def test_strict_preview_schema_cas_and_not_found_responses(self):
        base, current = self.urls()
        url = base + "/index-garbage-collection"
        headers = self.headers("admin-secret")
        preview = self.client.post(url, headers=headers, json={})
        self.assertTrue(preview.json()["dry_run"])
        for bad in ({"dry_run": "false"}, {"dry_run": False}, {"keep_generations": True},
                    {"keep_generations": 0}, {"keep_generations": "2"}, {"unknown": 1}):
            self.assertEqual(422, self.client.post(url, headers=headers, json=bad).status_code, bad)
        self.assertEqual(409, self.client.post(url, headers=headers, json={"dry_run": False, "expected_generation_id": "stale"}).status_code)
        rollback = base + "/index-generations/rollback"
        self.assertEqual(422, self.client.post(rollback, headers=headers,
            json={"generation_id": current, "expected_generation_id": current, "reason": "   "}).status_code)
        self.assertEqual(404, self.client.post(rollback, headers=headers,
            json={"generation_id": "missing", "expected_generation_id": current, "reason": "review"}).status_code)
        self.assertEqual(404, self.client.get("/v1/knowledge-bases/missing/index-generations", headers=self.headers("read-secret")).status_code)

    def test_vector_failure_returns_retryable_status_without_exposing_exception(self):
        base, current = self.urls()
        with patch.object(self.app.state.knowledge.vector_store, "chunk_ids", side_effect=RuntimeError("private-dsn")):
            for suffix, payload in (("/index-garbage-collection", {}),
                                    ("/index-generations/rollback", {"generation_id": current, "expected_generation_id": current, "reason": "review"})):
                result = self.client.post(base + suffix, headers=self.headers("admin-secret"), json=payload)
                self.assertEqual(503, result.status_code)
                self.assertNotIn("private-dsn", result.text)


if __name__ == "__main__":
    unittest.main()
