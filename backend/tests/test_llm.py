import json
import unittest

from backend.llm import (
    ExtractiveLlmProvider,
    LlmError,
    OpenAICompatibleLlmProvider,
    estimate_tokens,
)


class LlmTests(unittest.TestCase):
    def test_extractive_provider_returns_only_supplied_source(self):
        provider = ExtractiveLlmProvider()
        messages = [
            {"role": "system", "content": "grounded"},
            {
                "role": "user",
                "content": 'Question\n<source chunk_id="one">\nEvidence text\n</source>',
            },
        ]
        result = provider.generate(messages, max_tokens=100)
        self.assertEqual("Evidence text", result.text)
        self.assertGreater(result.usage["completion_tokens"], 0)
        self.assertEqual(
            "Evidence text", "".join(provider.stream(messages, max_tokens=100))
        )
        self.assertLessEqual(
            estimate_tokens(provider.generate(messages, max_tokens=2).text), 2
        )

    def test_openai_compatible_generate_and_stream(self):
        captured = []

        def transport(request, _timeout):
            captured.append(json.loads(request.data))
            return json.dumps(
                {
                    "choices": [{"message": {"content": "Grounded answer"}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 3},
                }
            ).encode()

        def stream_transport(request, _timeout):
            captured.append(json.loads(request.data))
            return [
                b'data: {"choices":[{"delta":{"content":"Grounded "}}]}\n',
                b'data: {"choices":[{"delta":{"content":"answer"}}]}\n',
                b"data: [DONE]\n",
            ]

        provider = OpenAICompatibleLlmProvider(
            base_url="https://llm.example/v1",
            api_key="secret",
            model="chat-model",
            transport=transport,
            stream_transport=stream_transport,
        )
        messages = [{"role": "user", "content": "question"}]
        result = provider.generate(messages, max_tokens=200)
        streamed = "".join(provider.stream(messages, max_tokens=200))

        self.assertEqual("Grounded answer", result.text)
        self.assertEqual(20, result.usage["prompt_tokens"])
        self.assertEqual("Grounded answer", streamed)
        self.assertFalse(captured[0]["stream"])
        self.assertTrue(captured[1]["stream"])
        self.assertEqual(0, captured[0]["temperature"])

    def test_token_estimator_is_conservative_for_cjk(self):
        self.assertGreaterEqual(estimate_tokens("中文知识库"), 5)
        self.assertEqual(1, estimate_tokens("test"))

    def test_generate_accepts_nested_usage_details_without_double_counting(self):
        # Ollama 0.35.1 returns cached-token details even for ordinary generation.
        payload = {
            "choices": [{"finish_reason": "stop", "message": {"content": "24 V"}}],
            "usage": {
                "prompt_tokens": 207,
                "prompt_tokens_details": {"cached_tokens": 206},
                "completion_tokens": 52,
                "completion_tokens_details": {"reasoning_tokens": 0},
                "total_tokens": 259,
            },
        }
        provider = OpenAICompatibleLlmProvider(
            base_url="http://127.0.0.1:11434/v1", api_key=None, model="local-instruct",
            transport=lambda *_: json.dumps(payload).encode(),
        )
        result = provider.generate([{"role": "user", "content": "voltage?"}], max_tokens=100)
        self.assertEqual("24 V", result.text)
        self.assertEqual({"prompt_tokens": 207, "completion_tokens": 52, "total_tokens": 259}, result.usage)

    def test_generate_rejects_invalid_top_level_token_counts(self):
        for count in (-1, True, 1.5, "52", {"cached_tokens": 52}):
            with self.subTest(count=count):
                payload = {
                    "choices": [{"message": {"content": "24 V"}}],
                    "usage": {"completion_tokens": count},
                }
                provider = OpenAICompatibleLlmProvider(
                    base_url="http://127.0.0.1:11434/v1", api_key=None, model="local-instruct",
                    transport=lambda *_: json.dumps(payload).encode(),
                )
                with self.assertRaises(LlmError):
                    provider.generate([{"role": "user", "content": "voltage?"}], max_tokens=100)


if __name__ == "__main__":
    unittest.main()
