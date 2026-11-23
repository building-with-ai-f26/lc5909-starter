"""Fire 30 create-trip calls at a deployed TrailTrain and print each status.

Usage:  python3 tests/live_rate_limit_check.py https://YOUR-APP.onrender.com
Expected: 10 x 201 (created), then 20 x 429 (refused by the rate limit).
(Not picked up by unittest discover: the file name does not start with "test".)
"""

import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1].rstrip("/")
counts = {}
for i in range(1, 31):
    req = urllib.request.Request(base + "/api/trips", data=json.dumps({"title": "rate limit test"}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            code, msg = r.status, "created"
    except urllib.error.HTTPError as e:
        code, msg = e.code, json.loads(e.read() or b"{}").get("error", "")
    counts[code] = counts.get(code, 0) + 1
    print(f"call {i:2d}: {code} {msg}")
print(f"\nSummary: {counts}  ->  {'RATE LIMIT WORKS' if counts.get(429, 0) >= 20 else 'CHECK THIS'}")
