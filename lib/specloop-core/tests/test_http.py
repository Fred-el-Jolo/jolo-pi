#!/usr/bin/env python3
"""HTTP retry helper tests — stdlib only, no network. Run: python3 test_http.py"""
import os
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import httputil as http  # noqa: E402


class _Resp:
    """Fake context-manager response (urlopen() return value)."""

    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code):
    req = type("R", (), {"full_url": "http://x"})()
    return urllib.error.HTTPError("http://x", code, "x", {}, None)


class HttpTests(unittest.TestCase):
    def test_success_no_retry(self):
        attempts = []

        def fake(req, timeout):
            attempts.append(1)
            return _Resp(b'{"data":[1]}')

        with patch("urllib.request.urlopen", fake):
            out = http.post_json("http://x", {"Authorization": "Bearer k"}, {"q": 1})
        self.assertEqual(out, {"data": [1]})
        self.assertEqual(len(attempts), 1)

    def test_retries_once_on_503_then_succeeds(self):
        attempts = []
        sleeps = []

        def fake(req, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                raise _http_error(503)
            return _Resp(b'{"ok":1}')

        with patch("urllib.request.urlopen", fake):
            out = http.post_json("http://x", {}, {}, sleep=sleeps.append)
        self.assertEqual(out, {"ok": 1})
        self.assertEqual(len(attempts), 2)
        self.assertEqual(len(sleeps), 1)  # backed off exactly once

    def test_no_retry_on_401(self):
        attempts = []

        def fake(req, timeout):
            attempts.append(1)
            raise _http_error(401)

        with patch("urllib.request.urlopen", fake):
            with self.assertRaises(RuntimeError) as cm:
                http.post_json("http://x", {}, {}, sleep=lambda *_: None)
        self.assertIn("HTTP 401", str(cm.exception))
        self.assertEqual(len(attempts), 1)  # caller's fault → no retry

    def test_retries_on_urlerror_timeout(self):
        attempts = []

        def fake(req, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                raise urllib.error.URLError("timed out")
            return _Resp(b'{"ok":1}')

        with patch("urllib.request.urlopen", fake):
            out = http.post_json("http://x", {}, {}, sleep=lambda *_: None)
        self.assertEqual(out, {"ok": 1})
        self.assertEqual(len(attempts), 2)

    def test_gives_up_after_retries_exhausted(self):
        attempts = []

        def fake(req, timeout):
            attempts.append(1)
            raise _http_error(503)

        with patch("urllib.request.urlopen", fake):
            with self.assertRaises(RuntimeError):
                http.post_json("http://x", {}, {}, retries=1, sleep=lambda *_: None)
        self.assertEqual(len(attempts), 2)  # initial + 1 retry


if __name__ == "__main__":
    unittest.main()
