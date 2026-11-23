# SECURITY.md: TrailTrain security audit

**Audit date:** Nov 23, 2026 · **Lane:** Beginner (one live Render web service) · **Auditor:** Emily Chen with Claude Code

## What the app holds
- **No database, no sign-in.** Trips live in server memory and disappear when the server restarts.
- A trip holds what friends type when they join: a first name, a starting station, a fitness level, and a budget number. **No emails, phone numbers, passwords, or payment data.**
- **Access model:** the trip link is the key. The ID is 12 random bytes (`secrets.token_urlsafe(12)`, about 96 bits), so trips cannot be listed or guessed.
- **Only secret:** `OPENROUTER_API_KEY`. It lives in `.env` locally and in Render's environment settings in production.

Because there is no database, the proof test is **"the rate limit stops 30 calls"**.

## What I checked
| # | Area | How I checked it |
|---|---|---|
| 1 | Secrets in git | Searched the full git history for `sk-or-` / key values: only the `.env.example` placeholder. Confirmed `.env` is git-ignored. |
| 2 | LLM cost abuse | Looked at `/api/parse`: anyone could call it in a loop and spend my OpenRouter credit. |
| 3 | Write-endpoint abuse | `/api/trips`, `/join`, `/delay` had no limit. A script could create unlimited trips and fill memory. |
| 4 | Request bodies | Tried huge bodies, non-JSON, a JSON array instead of an object, and wrong types (lists, objects) in fields. |
| 5 | XSS | Every place the page writes user or model text uses `innerHTML`. Checked that each one goes through `esc()`. |
| 6 | Trip ID guessing | The ID was `token_urlsafe(5)` (40 bits). |
| 7 | Prompt injection | The model only fills form fields. `llm.normalize()` validates every value (date, HH:MM, group size 1–30, supported route), and the organizer confirms before anything is saved. Train times never come from the model. |
| 8 | Response headers | Checked for clickjacking, MIME sniffing, and the trip link leaking via `Referer`. |
| 9 | Analytics privacy | PostHog events record which fields were parsed, never the typed description. |

## What I found and fixed
| Finding | Severity | Fix |
|---|---|---|
| `/api/parse` could be looped to burn LLM credit | High | Per-IP limit: **5 calls/min**. Also a **global cap of 200 AI calls/day** (`PARSE_DAILY_CAP`), which holds even if someone fakes their IP. |
| Unlimited trip creation, joins, and delays (memory DoS) | Medium | Per-IP limit: **10 write calls/min** returns `429`. Caps: 500 trips per server, 30 people per trip, 100 notifications per trip, delay of 1–240 min. |
| Huge or malformed bodies could raise errors or use memory | Medium | Bodies over 10 KB, invalid JSON, and non-object JSON all return `400`. Fields are cast to strings and times are checked with the HH:MM regex. |
| Trip ID was only 40 bits | Low | Raised to 96 bits. |
| No security headers | Low | Added `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `Referrer-Policy: no-referrer`. |
| Server only listened on `127.0.0.1:8000` | (deploy blocker) | Reads `HOST` and `PORT` from the environment; Render sets them. |
| XSS | None found | All dynamic HTML already went through `esc()`. |

## How it is proven
- `tests/test_security.py`, run with `python3 -m unittest discover tests`:
  - 30 create-trip calls give **10 × 201, then 20 × 429**.
  - 30 AI-parse calls give **25 × 429**. In this test the LLM is replaced with a stub, so it makes no network calls and costs nothing.
  - Oversized and non-object bodies are refused with **400**.
  - An unknown trip ID returns **404**.
- On the live site, `python3 tests/live_rate_limit_check.py https://lc5909-starter.onrender.com` prints every status and a summary line. The screenshot of the refusal is in the build submission.

## What is left (known risks)
- **Fakeable IP:** the per-IP limit trusts the first `X-Forwarded-For` value, which a client can fake to dodge it. The global daily AI cap still bounds spend. Next step: check how Render builds this header and use the entry its proxy adds.
- **Per-process limits:** counters and trips live in memory. A restart resets them, which also deletes every trip. This is acceptable for a class demo.
- **The link is the only key:** anyone holding a trip link can see the names and budgets in that trip, join it, and press "Simulate delay". This is fine for friends sharing a link; a real launch would need organizer-only actions.
- **No Content-Security-Policy yet:** the PostHog snippet is inline and loads from posthog.com, so a CSP needs testing so that session replay keeps working.
- **PostHog sees trip URLs:** pageview URLs contain the trip ID. Next step: mask or strip the path in PostHog.
- **Sample timetable:** the timetable is not verified against MTA. This is a safety risk for real trips (missing the last train), and the UI labels it on every plan.
- **HTTPS** is handled by Render, not by the app.
