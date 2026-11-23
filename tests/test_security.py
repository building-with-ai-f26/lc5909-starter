"""Security checks: the rate limit stops a burst of 30 calls, bad input is refused.

Starts the real server on a free local port (no network beyond localhost).
Run from the repo root:  python3 -m unittest discover tests
"""

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

import server  # noqa: E402


def post(base, path, body, raw=None):
    data = raw if raw is not None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


class SecurityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        cls._real_parse = server.llm.parse_trip_request
        server.llm.parse_trip_request = lambda text, route: {"fields": {}, "notes": []}  # no network, no cost
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        server.llm.parse_trip_request = cls._real_parse
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        server.HITS.clear()

    def test_30_create_calls_hit_rate_limit(self):
        codes = [post(self.base, "/api/trips", {"title": "burst"}) for _ in range(30)]
        self.assertEqual(codes[:10], [201] * 10)
        self.assertEqual(codes[10:], [429] * 20)

    def test_30_ai_parse_calls_hit_rate_limit(self):
        codes = [post(self.base, "/api/parse", {"text": "4 of us Saturday"}) for _ in range(30)]
        self.assertEqual(codes.count(429), 25)  # only 5 reach the LLM code path

    def test_oversized_and_non_object_bodies_refused(self):
        self.assertEqual(post(self.base, "/api/trips", None, raw=b"x" * 20_000), 400)
        self.assertEqual(post(self.base, "/api/trips", [1, 2]), 400)

    def test_unknown_trip_is_404(self):
        self.assertEqual(post(self.base, "/api/trips/not-a-real-id/join", {}), 404)


if __name__ == "__main__":
    unittest.main()
