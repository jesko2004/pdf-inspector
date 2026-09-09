import json
import unittest

from backend.llm import (
    ExtractiveLlmProvider,
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


if __name__ == "__main__":
    unittest.main()
