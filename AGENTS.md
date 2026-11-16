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
- **Run model evals:** not yet. The one model call (trip description parsing) is covered by deterministic validation tests in `tests/test_llm.py`; a 10-case eval comes in Build 4.

## Project Structure
```
app/
  server.py            HTTP server + JSON API (/api/route, /api/parse, /api/trips/...); trips live in memory
  llm.py               One OpenRouter call: trip description -> form fields; validates the model's JSON
  planner.py           Rules-only planner: trains, backup, last train home, delay re-plan, home-by warning
  data/route.json      Sample Cold Spring timetable (NOT verified against MTA)
  static/index.html    The whole local UI (vanilla HTML/JS) + PostHog snippet and custom events
docs/
  index.html           Product Page on GitHub Pages: pitch, living PRD, build log, PostHog snippet
  assets/              Screenshots used on the Product Page
tests/                 unittest suites for planner.py and llm.py (no network)
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
