"""TrailTrain local prototype server (Python standard library only).

Run:  python3 app/server.py   then open http://localhost:8000
Trips live in memory and are lost when the server stops.
"""

import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from collections import deque
from pathlib import Path
from urllib.parse import urlparse

import llm
import planner

HERE = Path(__file__).parent
ROUTE = json.loads((HERE / "data" / "route.json").read_text())
INDEX = (HERE / "static" / "index.html").read_bytes()
PORT = int(os.environ.get("PORT", "8000"))  # hosts like Render set PORT
HOST = os.environ.get("HOST", "127.0.0.1")  # set HOST=0.0.0.0 when deployed

# Abuse limits (see SECURITY.md). No database, so these are per server process.
MAX_BODY_BYTES = 10_000
MAX_TRIPS = 500
MAX_FRIENDS = 30
RATE_LIMITS = {"write": (10, 60), "parse": (5, 60)}  # bucket: (requests, per seconds) per client IP
PARSE_DAILY_CAP = int(os.environ.get("PARSE_DAILY_CAP", "200"))  # all users; caps OpenRouter spend
FEED_PATH = HERE / "data" / "delay_feed.json"  # simulated delay feed: {"train_id": minutes}
FEED_CHECK_SEC = 10
llm.load_env()

TRIPS = {}
LOCK = threading.Lock()
HITS = {}  # (bucket, ip) -> deque of request times
PARSE_DAY = {"day": None, "count": 0}
RATE_LOCK = threading.Lock()


def rate_limited(bucket, ip, now=None):
    """True if this IP used up its requests for this bucket in the time window."""
    now = time.time() if now is None else now
    limit, window = RATE_LIMITS[bucket]
    with RATE_LOCK:
        q = HITS.setdefault((bucket, ip), deque())
        while q and q[0] <= now - window:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        if len(HITS) > 10_000:  # forget idle IPs so the table cannot grow forever
            for k in [k for k, v in HITS.items() if not v or v[-1] <= now - 3600]:
                del HITS[k]
        return False


def parse_budget_left():
    """Global daily cap on LLM calls, whatever IP they come from."""
    today = time.strftime("%Y-%m-%d")
    with RATE_LOCK:
        if PARSE_DAY["day"] != today:
            PARSE_DAY.update(day=today, count=0)
        if PARSE_DAY["count"] >= PARSE_DAILY_CAP:
            return False
        PARSE_DAY["count"] += 1
        return True


def replan(trip):
    """Recompute the plan; if the main plan changed, notify everyone."""
    new = planner.make_plan(ROUTE, trip["friends"], trip["earliest_departure"], trip["delays"], trip["home_by"])
    msg = planner.describe_change(trip["plan"], new)
    if msg:
        trip["notifications"].append(msg)
    trip["plan"] = new


def check_feed(trip, feed):
    """Agent step: apply new delays from the feed, then re-plan on its own.

    trip["feed_seen"] remembers what was already handled, so the same
    delay never triggers a second alert. Returns True if anything changed.
    """
    plan = trip["plan"]
    if not plan or not plan.get("ok"):
        return False
    seen = trip.setdefault("feed_seen", {})
    changed = False
    for train, minutes in feed.items():
        delta = int(minutes) - seen.get(train, 0)
        if delta == 0:
            continue
        seen[train] = int(minutes)
        trip["delays"][train] = trip["delays"].get(train, 0) + delta
        trip["notifications"].append(f"Detected: {train} delayed {int(minutes)} min (delay feed).")
        changed = True
    if changed:
        replan(trip)
    return changed


def read_feed():
    try:
        return json.loads(FEED_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def monitor_loop():
    """Background watcher: every FEED_CHECK_SEC, check every trip against the feed."""
    while True:
        feed = read_feed()
        with LOCK:
            for trip in TRIPS.values():
                check_feed(trip, feed)
        time.sleep(FEED_CHECK_SEC)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if status == 429:
            self.send_header("Retry-After", "60")
        self.end_headers()
        self.wfile.write(data)

    def _client_ip(self):
        # Behind Render's proxy the real client is the first X-Forwarded-For entry.
        # A client can fake this header; PARSE_DAILY_CAP still bounds spend (SECURITY.md).
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY_BYTES:
            raise ValueError("too large")
        body = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("not an object")
        return body

    def _trip(self, parts):
        trip = TRIPS.get(parts[2]) if len(parts) > 2 else None
        if not trip:
            self._send(404, {"error": "Trip not found. The server may have restarted."})
        return trip

    def do_GET(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if parts == [""]:
            return self._send(200, INDEX, "text/html; charset=utf-8")
        if parts == ["api", "route"]:
            return self._send(200, {
                "name": ROUTE["name"], "stations": ROUTE["stations"],
                "fitness": list(ROUTE["hike_minutes"]), "data_status": ROUTE["data_status"],
            })
        if parts[:2] == ["api", "trips"] and len(parts) == 3:
            with LOCK:
                trip = self._trip(parts)
                if trip:
                    self._send(200, trip)
            return
        self._send(404, {"error": "Not found"})

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        ip = self._client_ip()
        bucket = "parse" if parts == ["api", "parse"] else "write"
        if rate_limited(bucket, ip):
            return self._send(429, {"error": "Too many requests. Wait a minute and try again."})
        try:
            body = self._body()
        except ValueError:  # includes JSONDecodeError and a bad Content-Length
            self.close_connection = True
            return self._send(400, {"error": "Invalid request body"})

        if parts == ["api", "parse"]:
            text = str(body.get("text") or "").strip()[:500]
            if not text:
                return self._send(400, {"error": "Describe your trip first."})
            if not parse_budget_left():
                return self._send(429, {"error": "Daily AI limit reached. Fill in the form by hand."})
            try:
                return self._send(200, llm.parse_trip_request(text, ROUTE))
            except llm.LLMError as e:
                status = 503 if "OPENROUTER_API_KEY" in str(e) else 502
                return self._send(status, {"error": str(e)})

        if parts == ["api", "trips"]:
            try:
                group_size = int(body.get("group_size") or 0) or None
            except (TypeError, ValueError):
                group_size = None
            trip_id = secrets.token_urlsafe(12)  # the link is the only key to a trip
            trip = {
                "id": trip_id,
                "title": str(body.get("title") or "Weekend hike").strip()[:80],
                "date": str(body.get("date") or "")[:10],
                "earliest_departure": dep if llm.TIME_RE.match(dep := str(body.get("earliest_departure") or "")) else "08:30",
                "group_size": group_size,
                "home_by": hb if llm.TIME_RE.match(hb := str(body.get("home_by") or "")) else None,
                "route": ROUTE["name"],
                "friends": [], "delays": {}, "notifications": [], "plan": None,
            }
            with LOCK:
                if len(TRIPS) >= MAX_TRIPS:
                    return self._send(503, {"error": "Too many trips on this demo server. Try again later."})
                TRIPS[trip_id] = trip
            return self._send(201, {"id": trip_id})

        if parts[:2] != ["api", "trips"] or len(parts) != 4:
            return self._send(404, {"error": "Not found"})

        with LOCK:
            trip = self._trip(parts)
            if not trip:
                return
            action = parts[3]

            if action == "join":
                name = str(body.get("name") or "").strip()[:40]
                station, fitness = str(body.get("station")), str(body.get("fitness"))
                try:
                    budget = float(body.get("budget"))
                except (TypeError, ValueError):
                    budget = -1
                if not name or station not in ROUTE["stations"] or fitness not in ROUTE["hike_minutes"] or budget < 0:
                    return self._send(400, {"error": "Please fill in name, station, fitness, and budget."})
                if len(trip["friends"]) >= MAX_FRIENDS and all(f["name"] != name for f in trip["friends"]):
                    return self._send(400, {"error": f"A trip can have at most {MAX_FRIENDS} people."})
                trip["friends"] = [f for f in trip["friends"] if f["name"] != name]
                trip["friends"].append({"name": name, "station": station, "fitness": fitness, "budget": budget})
                trip["plan"] = planner.make_plan(
                    ROUTE, trip["friends"], trip["earliest_departure"], trip["delays"], trip["home_by"]
                )
                return self._send(200, trip)

            if action == "delay":
                plan = trip["plan"]
                if not plan or not plan.get("ok"):
                    return self._send(400, {"error": "There is no plan to delay yet."})
                try:
                    minutes = int(body.get("minutes") or 70)
                except (TypeError, ValueError):
                    minutes = 70
                minutes = max(1, min(minutes, 240))
                if len(trip["notifications"]) >= 100:
                    return self._send(400, {"error": "Too many delays on this trip."})
                train = plan["main"]["train"]
                trip["delays"][train] = trip["delays"].get(train, 0) + minutes
                trip["notifications"].append(f"Alert: {train} is delayed {minutes} min (simulated).")
                replan(trip)
                return self._send(200, trip)

        self._send(404, {"error": "Not found"})

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet


if __name__ == "__main__":
    threading.Thread(target=monitor_loop, daemon=True).start()
    print(f"TrailTrain running at http://localhost:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
