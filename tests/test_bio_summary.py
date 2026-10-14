import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import URLError

from tools.bio_summary import BioSummarizer, BioSummaryError


class BioSummaryTests(unittest.TestCase):
    def test_environment_settings(self):
        settings = {
            "AI_SUMMARY_API_KEY": "test-key",
            "AI_SUMMARY_API_BASE": "https://example.test/v1/chat/completions",
            "AI_SUMMARY_MODEL": "test-model",
            "AI_SUMMARY_TIMEOUT": "45",
        }
        with patch.dict(os.environ, settings, clear=True):
            summarizer = BioSummarizer.from_settings(None, None, None)
            self.assertEqual(summarizer.api_key, "test-key")
            self.assertEqual(summarizer.api_base, "https://example.test/v1/chat/completions")
            self.assertEqual(summarizer.model, "test-model")
            self.assertEqual(summarizer.timeout, 45)
            override = BioSummarizer.from_settings("https://override.test/chat", "override", 60)
            self.assertEqual(override.model, "override")
            self.assertEqual(override.timeout, 60)

    def test_linkedin_crawler_environment_names_are_not_supported(self):
        with patch.dict(os.environ, {
            "LINKEDIN_CRAWLER_AI_API_KEY": "legacy-key",
            "LINKEDIN_CRAWLER_AI_API_BASE": "https://example.test/chat",
            "LINKEDIN_CRAWLER_AI_MODEL": "legacy-model",
        }, clear=True), self.assertRaisesRegex(BioSummaryError, "AI_SUMMARY_API_KEY"):
            BioSummarizer.from_settings(None, None, None)

    def test_request_and_response_are_validated_without_network(self):
        summarizer = BioSummarizer("test-key", "https://example.test/chat", "test-model", 30)
        response = io.BytesIO(json.dumps({"choices": [{"message": {"content": "Technology professional."}}]}).encode())
        source = "Technology delivery and project management. " * 20
        with patch("tools.bio_summary.urlopen", return_value=response) as request:
            self.assertEqual(summarizer.summarize(source), "Technology professional.")
        payload = json.loads(request.call_args.args[0].data)
        self.assertFalse(payload["store"])
        self.assertEqual(payload["model"], "test-model")
        self.assertIn(source, payload["messages"][1]["content"])
        self.assertEqual(request.call_args.kwargs["timeout"], 30)

    def test_missing_key_and_invalid_settings_fail_explicitly(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(BioSummaryError):
            BioSummarizer.from_settings(None, None, None)
        with patch.dict(os.environ, {"AI_SUMMARY_API_KEY": "test"}, clear=True):
            for endpoint in ("http://example.test/chat", "https://github.com/chat", "not-a-url"):
                with self.subTest(endpoint=endpoint), self.assertRaises(BioSummaryError):
                    BioSummarizer.from_settings(endpoint, None, None)
            with self.assertRaises(BioSummaryError):
                BioSummarizer.from_settings(None, None, 0)

    def test_invalid_length_is_retried_with_stricter_limit(self):
        summarizer = BioSummarizer("test-key", "https://example.test/chat", "test-model", 30)
        source = "Technology delivery and project management. " * 20
        responses = [
            io.BytesIO(json.dumps({"choices": [{"message": {"content": "experience " * 101}}]}).encode()),
            io.BytesIO(json.dumps({"choices": [{"message": {"content": "> Technology professional."}}]}).encode()),
        ]
        with patch("tools.bio_summary.urlopen", side_effect=responses) as request:
            self.assertEqual(summarizer.summarize(source), "Technology professional.")
        self.assertEqual(request.call_count, 2)
        retry_payload = json.loads(request.call_args.args[0].data)
        self.assertIn("50 words", retry_payload["messages"][0]["content"])

    def test_non_shorter_response_error_includes_lengths(self):
        summarizer = BioSummarizer("test-key", "https://example.test/chat", "test-model", 30)
        data = {"choices": [{"message": {"content": "Original bio."}}]}
        responses = [io.BytesIO(json.dumps(data).encode()) for _ in range(2)]
        with patch("tools.bio_summary.urlopen", side_effect=responses), self.assertRaisesRegex(
            BioSummaryError, "13 characters for a 13-character source.*after one retry",
        ):
            summarizer.summarize("Original bio.")

    def test_provider_errors_and_invalid_outputs_are_not_silent_fallbacks(self):
        summarizer = BioSummarizer("test-key", "https://example.test/chat", "test-model", 30)
        with patch("tools.bio_summary.urlopen", side_effect=URLError("Unavailable")), self.assertRaises(BioSummaryError):
            summarizer.summarize("Source text")
        for data in (
            {}, {"choices": []},
            {"choices": [{"message": {"content": ""}}]},
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": "too long " * 101}}]},
        ):
            with self.subTest(data=data):
                responses = [io.BytesIO(json.dumps(data).encode()) for _ in range(2)]
                with patch("tools.bio_summary.urlopen", side_effect=responses), self.assertRaises(BioSummaryError):
                    summarizer.summarize("Original bio.")
