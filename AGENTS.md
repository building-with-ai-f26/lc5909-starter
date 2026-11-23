# AGENTS.md — Coding Agent Operating Manual

> Give this file to your coding agent and check that it is using these instructions. Keep the stack, commands, and ground rules current.

## 1. Project Overview
- **What this repo builds:** TrailTrain, a planner that helps car-free NYC friend groups plan transit-reachable hiking day trips around the last train home, and re-plans when a train is delayed.
- **Primary user & core workflow:** [See the living PRD in `docs/index.html`]
- **Tech stack:** Python 3 standard library only (`http.server`), one vanilla HTML/JS page, in-memory trips. One LLM call (OpenRouter, `app/llm.py`) turns a plain-language trip description into form fields; every train time still comes from rules in `app/planner.py` over `app/data/route.json` (sample timetable, not verified).

## 2. Commands
- **Install dependencies:** none (needs Python 3.9+)
- **Set up secrets:** `cp .env.example .env`, then put your OpenRouter key in `.env` (never commit it). Without a key the app still works; only "Fill from description" shows an error.
- **Run locally:** `python3 app/server.py`, then open http://localhost:8000
- **Run deterministic tests:** `python3 -m unittest discover tests`
- **Run the live rate-limit check:** `python3 tests/live_rate_limit_check.py https://lc5909-starter.onrender.com` (expects 10 × 201, then 20 × 429)
- **Run model evals:** not yet. The one model call (trip description parsing) is covered by deterministic validation tests in `tests/test_llm.py`; a 10-case eval comes in Build 4.

## Project Structure
```
app/
  server.py            HTTP server + JSON API (/api/route, /api/parse, /api/trips/...); trips live in memory
  llm.py               One OpenRouter call: trip description -> form fields; validates the model's JSON
  planner.py           Rules-only planner: trains, backup, last train home, delay re-plan, home-by warning
  data/route.json      Sample Cold Spring timetable (NOT verified against MTA)
  data/delay_feed.json Simulated delay feed {train_id: minutes}; server checks it every 10s and re-plans
  static/index.html    The whole local UI (vanilla HTML/JS) + PostHog snippet and custom events
docs/
  index.html           Product Page on GitHub Pages: pitch, living PRD, build log, PostHog snippet
  assets/              Screenshots used on the Product Page
tests/                 unittest suites for planner, llm, and security (rate limit, bad input; no network)
render.yaml            Render deploy config (free web service, no database)
SECURITY.md            Security audit: checked, found, fixed, left
journal/               Build journals (one file per build)
.env.example           Variables to copy into a local, git-ignored .env
```
- **Analytics:** PostHog web snippet in both `app/static/index.html` and `docs/index.html`. The `phc_` project key is public by design; never commit a personal API key.

## 3. Non-Negotiable Engineering Rules
1. **Plan before coding:** Before touching multiple files, propose a brief plan and wait for approval.
2. **Small batches:** Make small, focused changes that can be reviewed and explained by a human in a single Pull Request.
3. **Explainability:** Avoid unnecessary abstractions or dependencies. Help the human builder understand the main components, what changed, why it matters, what could break, and how it was checked.
4. **Verify changes:** Run relevant checks. For a reproducible logic bug, use a failing test to demonstrate the fix when practical. Record manual checks and known limitations; follow the selected Build 4 evaluation track.
5. **Zero secrets in code:** Never hardcode API keys, tokens, or credentials. Always read from environment variables (`.env`) and update `.env.example` when new variables are needed.
6. **Stop when looping:** If a fix fails twice in a row, stop, summarize what failed, and ask the human before trying a third approach.
7. **Clean up what you start (from a real mistake):** When you start a local server for a manual check, keep its PID in a shell variable (`python3 app/server.py & SP=$!`) and `kill $SP` in the same command. Afterwards, run `pgrep -fl app/server.py` to confirm nothing is left running. *Why:* on Nov 22 the agent wrote the PID to a scratch folder that did not exist, so the chained commands stopped early and the server kept running in the background on port 8000.
8. **Never call paid APIs in tests:** Stub `llm.parse_trip_request` in any test that goes through `/api/parse`. *Why:* the first version of the rate-limit test let 5 calls reach OpenRouter whenever `.env` had a key. The giveaway was that a run that should take 0.5s took 7.8s.

## 4. Shipping
- **Host:** Render free web service, built from `render.yaml`. Start command: `python3 app/server.py` with `HOST=0.0.0.0`; Render sets `PORT`.
- **Secrets:** `OPENROUTER_API_KEY` is set only in the Render dashboard (Environment). Never in git, never in `render.yaml`.
- **Flow:** branch → PR → `python3 -m unittest discover tests` passes → the human merges to `main` → the human clicks **Manual Deploy** on Render.
- **After every deploy:** open the live URL on a phone, create a trip, and join it. Run `tests/live_rate_limit_check.py <live-url>` and check that a PostHog session replay appears.
- **Known limits:** the free tier sleeps when idle (the first load takes about 50s), and a restart wipes all trips and rate-limit counters.

## 5. Ask me first
Stop and ask the human before you:
- Merge to `main`, deploy, or change anything in the Render or PostHog dashboards.
- Add, rotate, or ask for any secret or API key, or change `.env` or the Render environment variables.
- Add a dependency, a database, sign-in, or a new paid API call.
- Loosen a security limit (rate limits, body size, caps) or delete a test.
- Delete files, rewrite git history, or force-push.
- Change what PostHog records about users.
