"""TrailTrain local prototype server (Python standard library only).

Run:  python3 app/server.py   then open http://localhost:8000
Trips live in memory and are lost when the server stops.
"""

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import planner

HERE = Path(__file__).parent
ROUTE = json.loads((HERE / "data" / "route.json").read_text())
INDEX = (HERE / "static" / "index.html").read_bytes()
PORT = 8000

TRIPS = {}
LOCK = threading.Lock()


def replan(trip):
    """Recompute the plan; if the main plan changed, notify everyone."""
    new = planner.make_plan(ROUTE, trip["friends"], trip["earliest_departure"], trip["delays"])
    msg = planner.describe_change(trip["plan"], new)
    if msg:
        trip["notifications"].append(msg)
    trip["plan"] = new


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

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
        try:
            body = self._body()
        except json.JSONDecodeError:
            return self._send(400, {"error": "Invalid JSON"})

        if parts == ["api", "trips"]:
            trip_id = secrets.token_urlsafe(5)
            trip = {
                "id": trip_id,
                "title": (body.get("title") or "Weekend hike").strip()[:80],
                "date": body.get("date") or "",
                "earliest_departure": body.get("earliest_departure") or "08:30",
                "route": ROUTE["name"],
                "friends": [], "delays": {}, "notifications": [], "plan": None,
            }
            with LOCK:
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
                name = (body.get("name") or "").strip()[:40]
                station, fitness = body.get("station"), body.get("fitness")
                try:
                    budget = float(body.get("budget"))
                except (TypeError, ValueError):
                    budget = -1
                if not name or station not in ROUTE["stations"] or fitness not in ROUTE["hike_minutes"] or budget < 0:
                    return self._send(400, {"error": "Please fill in name, station, fitness, and budget."})
                trip["friends"] = [f for f in trip["friends"] if f["name"] != name]
                trip["friends"].append({"name": name, "station": station, "fitness": fitness, "budget": budget})
                trip["plan"] = planner.make_plan(ROUTE, trip["friends"], trip["earliest_departure"], trip["delays"])
                return self._send(200, trip)

            if action == "delay":
                plan = trip["plan"]
                if not plan or not plan.get("ok"):
                    return self._send(400, {"error": "There is no plan to delay yet."})
                minutes = int(body.get("minutes") or 70)
                train = plan["main"]["train"]
                trip["delays"][train] = trip["delays"].get(train, 0) + minutes
                trip["notifications"].append(f"Alert: {train} is delayed {minutes} min (simulated).")
                replan(trip)
                return self._send(200, trip)

        self._send(404, {"error": "Not found"})

    def log_message(self, fmt, *args):
        pass  # keep the terminal quiet


if __name__ == "__main__":
    print(f"TrailTrain running at http://localhost:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
