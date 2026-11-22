#!/usr/bin/env python3
"""
test_context7_docs.py
Unit and integration test suite for Context7 documentation lookup tool.
"""

import asyncio
import json
import subprocess
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from tools.context7_docs import (
    Context7APIError,
    Context7ConnectionError,
    Context7Error,
    LibraryCandidate,
    _extract_text_content,
    _parse_libraries_output,
    _parse_sse_response,
    _pick_best_candidate,
    async_query_library_docs,
    async_resolve_library_id,
    query_docs,
    query_library_docs,
    resolve_library_id,
)


class TestContext7DocsParsers(unittest.TestCase):
    """Test local parsers, models, and candidate ranking logic."""

    def test_parse_sse_response_success(self):
        sse_text = 'event: message\ndata: {"result":{"content":[{"type":"text","text":"hello world"}]}}\n\n'
        parsed = _parse_sse_response(sse_text)
        self.assertIn("result", parsed)
        content = _extract_text_content(parsed)
        self.assertEqual(content, "hello world")

    def test_parse_plain_json_response(self):
        json_text = json.dumps({"result": {"content": [{"type": "text", "text": "plain json content"}]}})
        parsed = _parse_sse_response(json_text)
        content = _extract_text_content(parsed)
        self.assertEqual(content, "plain json content")

    def test_extract_text_content_error_raises(self):
        err_response = {"error": {"code": -32000, "message": "Invalid library"}}
        with self.assertRaises(Context7APIError):
            _extract_text_content(err_response)

    def test_parse_libraries_output(self):
        sample_output = """Available Libraries:

- Title: Aiogram
- Context7-compatible library ID: /aiogram/aiogram
- Description: aiogram is an asynchronous Python framework.
- Code Snippets: 3478
- Source Reputation: High
- Benchmark Score: 62.85
- Versions: v2.25.1, v3.23.0
----------
- Title: Aiogram Docs
- Context7-compatible library ID: /websites/aiogram_dev_en
- Description: Official docs for aiogram.
- Code Snippets: 9796
- Source Reputation: High
- Benchmark Score: 71.28
- Versions: v3.25.0
"""
        candidates = _parse_libraries_output(sample_output)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].id, "/aiogram/aiogram")
        self.assertEqual(candidates[0].snippets, 3478)
        self.assertEqual(candidates[0].benchmark_score, 62.85)
        self.assertEqual(candidates[1].id, "/websites/aiogram_dev_en")

    def test_pick_best_candidate_ranks_by_score_and_snippets(self):
        candidates = [
            LibraryCandidate(id="/unrelated/tool", title="Unrelated Tool", benchmark_score=99.0),
            LibraryCandidate(id="/aiogram/aiogram", title="Aiogram Repo", benchmark_score=62.0, snippets=3000),
            LibraryCandidate(id="/websites/aiogram_dev_en", title="Aiogram Docs", benchmark_score=75.0, snippets=9000),
        ]
        best = _pick_best_candidate(candidates, "aiogram")
        self.assertIsNotNone(best)
        # Should filter out unrelated candidates and choose highest scoring matching candidate
        self.assertEqual(best.id, "/websites/aiogram_dev_en")

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            resolve_library_id("")
        with self.assertRaises(ValueError):
            query_docs("", "test")
        with self.assertRaises(ValueError):
            query_docs("/aiogram/aiogram", "")


class TestContext7DocsLiveIntegration(unittest.TestCase):
    """Test live calls to Context7 MCP endpoint."""

    def test_sync_resolve_library_id(self):
        candidates = resolve_library_id("aiogram", "TelegramConflictError")
        self.assertTrue(len(candidates) > 0)
        first_ids = [c.id for c in candidates]
        self.assertTrue(any("aiogram" in cid.lower() for cid in first_ids))

    def test_sync_query_library_docs(self):
        docs = query_library_docs("aiogram", "TelegramConflictError")
        self.assertIsInstance(docs, str)
        self.assertTrue(len(docs) > 100)
        self.assertTrue(
            "TelegramConflictError" in docs or "Conflict" in docs or "aiogram" in docs.lower()
        )

    def test_async_query_library_docs(self):
        async def run_async():
            return await async_query_library_docs("aiohttp", "ClientSession")

        docs = asyncio.run(run_async())
        self.assertIsInstance(docs, str)
        self.assertTrue(len(docs) > 100)
        self.assertTrue("ClientSession" in docs or "aiohttp" in docs.lower())

    def test_cli_execution_standalone(self):
        cmd = [
            sys.executable,
            str(BASE_DIR / "tools" / "context7_docs.py"),
            "aiogram",
            "TelegramConflictError",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, f"CLI error: {proc.stderr}")
        self.assertIn("TelegramConflictError", proc.stdout)

    def test_cli_resolve_only_json(self):
        cmd = [
            sys.executable,
            str(BASE_DIR / "tools" / "context7_docs.py"),
            "aiogram",
            "--resolve-only",
            "--json",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 0, f"CLI error: {proc.stderr}")
        data = json.loads(proc.stdout)
        self.assertIsInstance(data, list)
        self.assertTrue(len(data) > 0)
        self.assertIn("id", data[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
