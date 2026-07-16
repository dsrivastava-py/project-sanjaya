# Sanjaya — Manual QA Checklist (PRD §15)

The US-1…US-10 walkthrough. Run this end-to-end on a real Windows machine before
calling a build shippable. Automated coverage (unit / integration / prompt
regression / perf) lives in `tests/` and runs with `uv run pytest`; this file is
the **human** acceptance pass those tests can't fully stand in for.

**Setup once:** install per [`docs/INSTALL.md`](INSTALL.md), set `GROQ_API_KEY`,
load the browser extension, and let Sanjaya run for at least a few active hours
(or import a seeded day) so there is data to inspect.

Mark each row `PASS` / `FAIL` / `N/A` with a note.

---

## Automated pre-check (must be green first)

- [ ] `uv run pytest -q` → all tests pass.
- [ ] `cd dashboard; npm run build` → succeeds; Vite report shows JS+CSS
      gzip < 500 KB (§12).
- [ ] `GET /api/status` returns a `process` block with `rss_mb` < 150 and
      `cpu_ok: true` after the app has been idling a minute.

---

## US-1 — Everything is recorded automatically

- [ ] Start Sanjaya. Use 3–4 different apps (editor, browser, a document) for a
      few minutes each without touching Sanjaya.
- [ ] Open the dashboard → **Today**. Each app appears on the timeline with app
      name + window title; browser spans show the domain.
- [ ] Leave the machine idle > 5 min → that stretch shows as **Idle**, not as
      the last app.
- [ ] Lock the machine (Win+L) for a minute → shows as **Locked**, separated
      from idle.
- [ ] The day timeline has honest gaps for sleep/off time — **no interpolation**.

## US-2 — YouTube video title (not "chrome.exe")

- [ ] Play a YouTube video for ~1 min.
- [ ] Timeline span reads the **video title**; with the extension loaded, the
      **channel** is captured too (check the span popover detail).
- [ ] It is categorized (e.g. Entertainment) — not left as raw `chrome.exe`.

## US-3 — AI chat session + topic

- [ ] Have a short conversation in ChatGPT / Claude / Gemini / Perplexity
      (web or desktop app).
- [ ] The span is recognized as an **AI session** and shows the conversation
      **topic**, not just the browser/app name.

## US-4 — Web search query captured

- [ ] Run a Google/Bing search.
- [ ] The **query** appears (from the results-page title/URL) on the span.

## US-5 — File / document name captured

- [ ] Open a PDF, and edit a file in Word/Excel/PowerPoint/Notepad/VS Code.
- [ ] Each span shows the **file name**; for editors, the **project folder** is
      captured (span detail).

## US-6 — Stopwatch / timer reading (P1)

- [ ] Open **Windows Clock → Stopwatch**, let it run, then **pause or close** it.
- [ ] Today shows a captured **stopwatch reading** with the last visible value.
- [ ] Repeat with a known web timer (e.g. pomofocus.io) → last reading captured
      on pause/close.
- [ ] *If `uiautomation` is unavailable, Clock capture may no-op — that is an
      accepted P1 degrade, not a failure. Web-timer capture must still work.*

## US-7 — End-of-day journal (Groq)

- [ ] Tray → **Summarize now** (or wait for the nightly 21:30 job).
- [ ] Today shows: **category time totals**, a **timeline**, a written
      **journal entry** (marked ✦ AI), **highlights**, and a **focus score**.
- [ ] Every proper noun in the narrative corresponds to something you actually
      did (no invented apps/sites — this mirrors the automated hallucination
      heuristic).
- [ ] Turn off the network and Summarize → it queues, no crash; reconnect →
      the queue drains and the journal appears.

## US-8 — Fix anything in ≤3 clicks, Sanjaya learns

- [ ] Click a timeline block → popover. Change its **category** → chart updates
      immediately.
- [ ] Choose **"always classify like this"** → a learned rule is created; a
      later span of the same app/domain is auto-categorized the same way.
- [ ] Edit a **journal sentence** and add a **personal note** → both persist and
      survive a regenerate (note is kept, narrative is replaced).
- [ ] Add a **manual block** for offline work (e.g. a meeting) → the day still
      sums to 24h (overlap with idle is subtracted).
- [ ] **Review** page lists uncategorized / low-confidence spans; bulk-assign a
      group in one action.
- [ ] Every edit above is recorded (spot-check `edits_audit` or that undo/repeat
      behaves consistently).

## US-9 — Goals & streaks

- [ ] Create goals: "≥3h Placements daily", "≤1.5h Entertainment daily",
      "20h Agency weekly".
- [ ] **Goals** page shows meters and daily/weekly progress; the `at_most` cap
      goes red when exceeded.
- [ ] Streak flames (🔥) show current/best; a marked rest day does **not** break
      a streak.
- [ ] Today page goal meters match the Goals page.

## US-10 — Pause, exclude, export

- [ ] Tray → **Pause** (e.g. 30 min) → collector stops; status shows Paused;
      it auto-resumes.
- [ ] Settings → Privacy → add an **excluded app** (e.g. `1password.exe`) and an
      **excluded domain** (e.g. your bank). Use them.
- [ ] Confirm the excluded surfaces appear only as **`[excluded]`** (time is
      still counted) and their real title/URL is **never** in the DB or any AI
      payload (`data/ai_payloads/` if debug is on).
- [ ] Settings → Data → **Export JSON / CSV / Markdown** for a date range → each
      file downloads; the Markdown reads like a journal page.

---

## Cross-cutting checks

- [ ] **Autostart:** Settings/tray → "Start with Windows" ON → a `Sanjaya.lnk`
      exists in the Startup folder; reboot → Sanjaya launches on sign-in.
- [ ] **Single instance:** launching Sanjaya twice does not start a second
      collector.
- [ ] **App window:** tray → Open Dashboard opens a **chromeless window** (no
      tabs / address bar), not a normal browser tab (Edge/Chrome present).
- [ ] **First run:** on a fresh profile, the **onboarding overlay** appears once
      (seeded categories, GROQ pointer, extension pointer, start-on-boot) and
      does not reappear after "Start watching".
- [ ] **Perf soak:** leave Sanjaya running ~24h → the log records a soak line
      every 5 min; no `BUDGET BREACH` warnings (CPU < 0.5%, RAM < 150 MB).
- [ ] **Disk:** DB growth over a week is well under 10 MB/month typical (§12).

**Definition of done:** every US row PASS and all cross-cutting checks green.
