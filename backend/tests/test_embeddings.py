import json
import math
import unittest

from backend.embeddings import (
    EmbeddingError,
    HashEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
)


class EmbeddingTests(unittest.TestCase):
    def test_hash_embeddings_are_deterministic_normalized_and_distinct(self):
        provider = HashEmbeddingProvider(dimensions=32)
        first = provider.embed(["采购订单 PO-100", "设备维修手册"])
        second = provider.embed(["采购订单 PO-100", "设备维修手册"])

        self.assertEqual(first, second)
        self.assertNotEqual(first[0], first[1])
        self.assertAlmostEqual(1.0, math.sqrt(sum(value**2 for value in first[0])))

    def test_openai_compatible_provider_validates_and_orders_response(self):
        captured = {}

        def transport(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = json.loads(request.data)
            return json.dumps(
                {
                    "data": [
                        {"index": 1, "embedding": [0.0, 1.0]},
                        {"index": 0, "embedding": [1.0, 0.0]},
                    ]
                }
            ).encode()

        provider = OpenAICompatibleEmbeddingProvider(
            base_url="https://embedding.example/v1",
            api_key="secret",
            model="embed-model",
            dimensions=2,
            timeout_seconds=12,
            transport=transport,
        )
        vectors = provider.embed(["first", "second"])

        self.assertEqual([[1.0, 0.0], [0.0, 1.0]], vectors)
        self.assertEqual("https://embedding.example/v1/embeddings", captured["url"])
        self.assertEqual("Bearer secret", captured["authorization"])
        self.assertEqual(["first", "second"], captured["body"]["input"])
        self.assertEqual(2, captured["body"]["dimensions"])
        self.assertEqual(12, captured["timeout"])

    def test_openai_compatible_provider_rejects_bad_dimensions(self):
        provider = OpenAICompatibleEmbeddingProvider(
            base_url="http://localhost:8000/v1",
            api_key=None,
            model="local",
            dimensions=3,
            transport=lambda _request, _timeout: (
                b'{"data":[{"index":0,"embedding":[1,2]}]}'
            ),
        )
        with self.assertRaisesRegex(EmbeddingError, "dimension mismatch"):
            provider.embed(["text"])


if __name__ == "__main__":
    unittest.main()
