# Sanjaya

> *Your day, witnessed. Your journal, written.*

An AI-powered, zero-effort activity journal for Windows. A featherweight
background watcher records every foreground activity into a local SQLite
database; deterministic rules plus a Groq-hosted LLM turn the raw stream into
categorized time, a written daily journal, highlights, and goal progress —
rendered on a local dashboard. Everything is local except calls to the Groq API.

See [`PRD.md`](PRD.md) for the full product spec and build plan.

## Requirements

- Windows 10/11
- Python 3.12+ (developed on 3.13)
- [`uv`](https://docs.astral.sh/uv/)

## Quick start

```powershell
uv sync                              # create venv + install deps
copy .env.example .env               # then paste your GROQ_API_KEY
uv run python -m sanjaya --version   # sanity check
uv run python -m sanjaya --init-db   # create data/sanjaya.db
uv run python -m sanjaya             # start collector + tray
```

Dev helper: `./scripts/dev.ps1 <setup|run|version|initdb|test|lint>`.

While running, the local server lives at `http://127.0.0.1:8756` — `/api/status`
shows collector health, extension last-seen, AI queue depth, and process
CPU/RAM. The tray menu has Open Dashboard / Pause / Summarize now / Start with
Windows / Quit.

### Run it like a desktop app

`Open Dashboard` shows the SPA in a **chromeless Edge/Chrome `--app` window** (no
tabs or address bar) — controlled by `[server] app_window` in `config.toml`; set
it `false` for a normal browser tab. To launch Sanjaya from a Desktop/Start-Menu
icon (windowless, no console), run once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
```

New here? The plain-language, start-to-finish install guide is
[`docs/INSTALL.md`](docs/INSTALL.md). The manual acceptance walkthrough
(US-1…US-10) is [`docs/qa-checklist.md`](docs/qa-checklist.md).

## Browser extension (recommended)

For exact URLs, search queries, and YouTube title+channel fidelity, load the
MV3 extension unpacked from [`extension/`](extension/README.md): set the same
`SANJAYA_INGEST_TOKEN` in `extension/background.js` as in your `.env`, then
`chrome://extensions` → Developer mode → Load unpacked. Without it, Sanjaya
falls back to window-title parsing — everything still works at lower fidelity.

## AI (Groq)

Set `GROQ_API_KEY` in `.env`. Unknown spans are classified in batches
(`llama-3.1-8b-instant`); the daily journal is written nightly at 21:30
(`llama-3.3-70b-versatile`, configurable in `config.toml [ai]`) and on demand
via the tray or `POST /api/summary/{date}/generate`. Offline? Work queues in
`ai_queue` and drains when connectivity returns — the dashboard's deterministic
data never depends on AI. Set `debug_ai_payloads = true` to audit every
outbound payload in `data/ai_payloads/`.

## Data & privacy

All raw data stays in `data/sanjaya.db`. Only compressed, redaction-filtered
text summaries are sent to Groq. `data/`, `.env`, and `config.toml` are
gitignored.

## Dependency justifications (PRD §6 — keep under ~15 direct deps)

| Dependency | Why |
|---|---|
| `psutil` | pid→exe resolution, process info, self CPU/RAM metrics |
| `fastapi` | localhost JSON API + static SPA host |
| `uvicorn` | ASGI server for FastAPI |
| `apscheduler` | nightly summary / rollup / ai_queue drain jobs |
| `openai` | Groq API client (OpenAI-compatible `base_url`) |
| `python-dotenv` | load `GROQ_API_KEY` / `SANJAYA_INGEST_TOKEN` from `.env` |
| `tzdata` | IANA timezone db for `zoneinfo` on Windows |
| `pystray` | featherweight tray icon + menu |
| `Pillow` | render the tray icon image |
| `pywin32` | foreground window, idle time, session lock events |
| `winsdk` | media-session metadata (video/song titles incl. YouTube) |
| `uiautomation` | stopwatch reader for Windows Clock (best-effort, P1) |

`sqlite3`, `tomllib`, `zoneinfo`, `logging` are stdlib. Windows-only packages
carry `sys_platform == 'win32'` markers so the pure-logic test suite installs
and runs on any OS.

## Build status

- **Phase 0 — Scaffold** ✅ repo layout, DB schema + seeds, config, logging, CLI.
- **Phase 1 — Collector core** ✅ sampler, idle/lock, span builder, tray, single instance.
- **Phase 2 — Parsers + rules + focus** ✅ deterministic parsers, rule engine, focus score.
- **Phase 3 — Server + ingest + extension** ✅ FastAPI on 8756, `/api/status`,
  token-authed `/ingest/browser`, MV3 extension, ±3s span reconciliation.
- **Phase 4 — AI layer** ✅ Groq client (retries/backoff/Retry-After, JSON mode,
  redaction, token budget, payload debug dump), classifier job, ai_queue drain.
- **Phase 5 — Journal + insights** ✅ nightly daily journal (prompt B), weekly
  insight (prompt C), regenerate endpoints, deterministic focus score persisted,
  quiet-day handling, no-hallucination prompt-regression heuristic.
- **Phase 6 — Dashboard read views** ✅ React 18 + TS + Vite + Tailwind v4 +
  Recharts SPA in [`dashboard/`](dashboard/), built into `sanjaya/server/static`
  and served by FastAPI. Dark (default) + light themes via `data-theme`, §4.2
  tokens verbatim, §4.3 categorical palette (color follows category slot, idle
  neutral, no dual axes, tooltips + table view on every chart). Pages: Today
  (focus dial, day timeline with 2px gaps, category mix, AI journal ✦,
  highlights, goals), History (month heatmap + 7/30/90d stacked bars), Insights
  (weekly narrative, focus/active trends, small multiples, time-leak table).
  New read APIs: `/api/range`, `/api/categories`, `/api/insights/leaks`;
  `/api/day` gains goals/stopwatch/focus_components. Fonts bundled locally
  (@fontsource). Bundle ≈184 KB gz (budget 500). Keyboard: t/h/i/g/r/, + ←/→.

- **Phase 7 — Editability** ✅ every span is correctable and Sanjaya learns from
  it. Click a timeline block → popover editor (category chip grid, project with
  inline quick-create, free-text label, split-at-time, delete); "always classify
  like this" creates a `source='learned'` rule (priority 50, most-specific
  matcher: url_prefix → domain → exe) that retro-applies to still-unclassified
  spans and hot-reloads the collector's rule engine (`rules_version` handshake).
  Manual "＋ Add block" spans (`kind='manual'`) may overlap idle/locked — totals
  subtract the overlap so the day still sums to 24h. Journal narrative,
  highlights, and personal notes editable inline. Review page: uncategorized +
  low-confidence (<0.8) AI spans grouped by identity, one-click or bulk assign
  with one learned rule per distinct identity. Every mutation lands in
  `edits_audit`; charts update optimistically (TanStack Query rollback on
  error). New APIs: `PATCH/POST/DELETE /api/spans`, `POST /api/spans/{id}/split`,
  `GET /api/review`, `POST /api/review/assign`, `GET/POST /api/projects`.
- **Phase 8 — Goals & habits** ✅ goal engine in [`sanjaya/goals.py`](sanjaya/goals.py):
  daily/weekly (Mon–Sun)/monthly/yearly periods keyed by start date and aligned
  to `day_start_hour` (spans clipped at period bounds, §13.8), `at_least`
  targets and `at_most` caps, category- or project-scoped, `active_days` rest
  days that never break a streak. Streaks walk creation→today (met/missed/
  skipped; current `at_least` period pending, `at_most` over-cap missed
  irreversibly); closed periods cached write-through in `goal_progress`,
  precisely invalidated on span edits, healed by a nightly rollup job. Goals
  page: cards grouped by period with meter, 🔥 current/best streak, per-period
  history strip; full CRUD modal. Today page meters show streak flames and rest
  days. New APIs: `GET/POST/PATCH/DELETE /api/goals`, `GET /api/goals/progress`.
- **Phase 9 — Settings, privacy, export, polish** ✅ Settings page (§10.6):
  categories & projects managers, learned-rules table (filter, hit counts,
  delete → `rules_version` bump), privacy (exclude apps/domains, redaction
  regexes, retention months, debug/texture toggles), AI config (models, summary
  time, token cap, Test-connection), data export, and About/health. Privacy
  enforcement (§13.10): excluded exe/domain spans are still timed (honest time)
  but scrubbed to `title='[excluded]'` with url/detail/category nulled **before**
  the first persist, and never enqueue to the AI — verified in tests on both the
  DB and the AI-payload path. Settings overlay `config.toml` via a typed
  `settings` table (JSON/bool/int/str keys, unknown → 422). Exporters: JSON,
  CSV, and a per-day Markdown journal page (`GET /api/export?format=&from=&to=`,
  download attachment). Nightly retention trim drops raw spans older than
  `retention_months` **only** for days whose `day_summaries` exist (summaries
  kept forever; `0` = never). Stopwatch reader (P1): Windows Clock via UIA plus
  known web timers by title regex, recording pause/close transitions. Autostart
  toggle from tray + `POST /api/autostart`. New APIs: `GET/PATCH /api/settings`,
  `POST /api/settings/test-ai`, category/project/rule CRUD, `/api/autostart`,
  `/api/pause`, `/api/resume`, `/api/export`.
- **Phase 10 — Soak & ship** ✅ Self-metrics for the perf budget (§12): `/status`
  exposes a `process` block (CPU% normalized to total capacity, RSS MB, thread
  count, budget flags), and a scheduler job logs CPU/RSS vs budget every 5 min
  for the 24h soak (§15) — a `BUDGET BREACH` warning fires if collector+server
  exceeds <0.5% CPU / <150 MB. About card surfaces the live footprint. First-run
  onboarding overlay (gated by `settings.onboarding_done`): confirms seeded
  categories, points to the GROQ key in `.env` (with live Test-connection),
  points to the browser extension, and offers start-on-boot. README below is the
  fresh-machine install path (target: start-to-finish in <10 min). Bundle ≈197 KB
  gz (budget 500).

### Dashboard dev

```powershell
cd dashboard
npm install
npm run dev     # Vite on 5173, /api proxied to 127.0.0.1:8756
npm run build   # tsc + vite build -> ../sanjaya/server/static
```

Visual QA without real data: `uv run python scripts/preview_server.py`
(port 8899, seeded demo DB in temp dir — never touches `data/sanjaya.db`).
