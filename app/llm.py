"""Natural-language trip request -> trip form fields, via one LLM call.

The model only *parses* text. It never produces train times: the rules in
planner.py still build every plan. normalize() checks the model's output so
bad values never reach the form.

Needs OPENROUTER_API_KEY in .env (see .env.example).
"""

import json
import os
import re
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "anthropic/claude-haiku-5.5"
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class LLMError(Exception):
    """The LLM call failed or returned something unusable."""


def load_env(path=Path(__file__).resolve().parent.parent / ".env"):
    """Read KEY=VALUE lines from .env into os.environ (stdlib, no dotenv)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def build_prompt(route, today):
    return (
        "You turn a hiking trip request into JSON. Reply with ONLY a JSON object, no prose.\n"
        f"Today is {today.isoformat()} ({today.strftime('%A')}).\n"
        f"The only supported route is: {route['name']} (destination: {route['destination']}).\n"
        "Keys:\n"
        '  "title": short trip name (string)\n'
        '  "date": trip date as YYYY-MM-DD, or null if not stated\n'
        '  "earliest_departure": earliest time they can leave, 24h HH:MM, or null\n'
        '  "group_size": number of people as an integer, or null\n'
        '  "home_by": time they must be back home, 24h HH:MM, or null\n'
        '  "destination": the place they asked for, or null if not stated\n'
        "Never guess values that are not in the text; use null."
    )


def call_openrouter(text, route, today, timeout=20):
    """Send one chat request and return the model's raw text reply."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key or "replace-with-your-key" in key:
        raise LLMError("No OPENROUTER_API_KEY. Copy .env.example to .env and add your key.")
    body = {
        "model": os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": build_prompt(route, today)},
            {"role": "user", "content": text},
        ],
        "temperature": 0,
        "max_tokens": 300,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read())
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise LLMError(f"AI service returned HTTP {e.code}.") from e
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as e:
        raise LLMError("Could not reach the AI service.") from e


def normalize(raw, route, today):
    """Validate the model's raw text. Returns {"fields": {...}, "notes": [...]}.

    Only fields that pass validation are returned; problems become notes.
    """
    match = re.search(r"\{.*\}", raw or "", re.S)  # tolerate ```json fences or extra prose
    try:
        data = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise LLMError("The AI reply was not valid JSON. Please fill in the form by hand.")

    fields, notes = {}, []

    title = data.get("title")
    if isinstance(title, str) and title.strip():
        fields["title"] = title.strip()[:80]

    d = data.get("date")
    if d:
        try:
            parsed = date.fromisoformat(str(d))
            if parsed < today:
                notes.append(f"Date {parsed} is in the past, so it was left blank.")
            else:
                fields["date"] = parsed.isoformat()
        except ValueError:
            notes.append(f"Could not read the date \"{d}\".")

    for key, label in (("earliest_departure", "Earliest departure"), ("home_by", "Home-by time")):
        value = data.get(key)
        if value is None:
            continue
        value = str(value).strip()
        if len(value) == 4 and value[1] == ":":
            value = "0" + value  # 9:00 -> 09:00
        if TIME_RE.match(value):
            fields[key] = value
        else:
            notes.append(f"{label} \"{value}\" is not a valid time.")

    size = data.get("group_size")
    if size is not None:
        if isinstance(size, int) and not isinstance(size, bool) and 1 <= size <= 30:
            fields["group_size"] = size
        else:
            notes.append(f"Group size \"{size}\" doesn't look right.")

    dest = data.get("destination")
    if isinstance(dest, str) and dest.strip():
        if route["destination"].lower() not in dest.lower():
            notes.append(
                f"You asked for \"{dest.strip()}\", but only {route['name']} is supported right now."
            )

    return {"fields": fields, "notes": notes}


def parse_trip_request(text, route, today=None):
    today = today or date.today()
    return normalize(call_openrouter(text, route, today), route, today)
