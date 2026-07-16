# Getting Started with Sanjaya

> *Your day, witnessed. Your journal, written.*

This is the plain-language guide to installing and running **Sanjaya** on your
Windows desktop — and making it feel like a real app you double-click, not a
website you have to remember a URL for.

Take your time; the whole thing is about **10 minutes**.

---

## What you're installing

Sanjaya is a tiny background program for Windows. While your PC is on, it quietly
notes which app or website is in front of you and for how long. Each night (or
whenever you ask) it uses AI to turn that raw activity into a readable journal:
where your time went, what you got done, and how you're tracking against your
goals. **Everything stays on your computer** except the short text summaries sent
to Groq to write the journal.

It runs in three parts, all in one program:

1. A **background watcher** (the collector).
2. A **tray icon** (the little eye near your clock) — your control panel.
3. A **dashboard** — the screens you actually look at, shown in their own app
   window.

---

## Before you start

You need:

- **Windows 10 or 11.**
- **Internet** (only for installing, and for the AI journal).
- A **Groq API key** — free to create. Get one at
  <https://console.groq.com/keys>. (You can install without it and add it later;
  time tracking works regardless — only the AI journal waits.)
- **Microsoft Edge or Google Chrome** — Edge already comes with Windows. This is
  what shows the dashboard as an app window.

You do **not** need to know how to code. You'll copy-paste a few commands.

---

## Step 1 — Install `uv` (the installer helper)

`uv` sets up Python and all of Sanjaya's parts in one shot, so you don't have to
manage any of that by hand.

Open **PowerShell** (press Start, type *PowerShell*, hit Enter) and paste:

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Close and reopen PowerShell afterward so it picks up the new command.

## Step 2 — Get Sanjaya onto your PC

If you have the project as a folder already, skip to Step 3. Otherwise, in
PowerShell:

```powershell
cd $HOME\Documents
git clone <your-sanjaya-repo-url> sanjaya
cd sanjaya
```

(If you don't have `git`, download the project as a ZIP, unzip it into
`Documents\sanjaya`, then `cd` into that folder.)

## Step 3 — Install everything

From inside the `sanjaya` folder:

```powershell
uv sync
```

This creates a private Python environment and installs all dependencies. First
run takes a minute or two.

## Step 4 — Add your Groq key

Make your own settings file from the example, then open it:

```powershell
copy .env.example .env
notepad .env
```

In Notepad, replace the placeholder so the line looks like:

```
GROQ_API_KEY=gsk_your_real_key_here
```

Also set `SANJAYA_INGEST_TOKEN` to any long random text of your own (you'll reuse
it for the browser extension in Step 8). Save and close Notepad.

> No key yet? Leave it as-is for now. Sanjaya still tracks time; it will remind
> you to add the key, and the journal starts working the moment you do.

## Step 5 — Create the database

```powershell
uv run python -m sanjaya --init-db
```

You should see `database ready: ...\data\sanjaya.db`. This file is where all your
data lives, on your machine only.

## Step 6 — First run (test it works)

```powershell
uv run python -m sanjaya
```

A small **eye icon** appears near your clock (the system tray — you may need to
click the little "^" arrow to see it). That's Sanjaya running. Right-click it →
**Open Dashboard**. A window opens and walks you through a short first-run setup.

To stop it for now: right-click the eye → **Quit**.

---

## Step 7 — Make it a real desktop app (recommended)

So you can launch Sanjaya from a normal icon — no PowerShell, no console
window — install the shortcuts:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1
```

This puts a **Sanjaya** icon (the gold eye) on your **Desktop** and in the
**Start Menu**. From now on:

- **Double-click the Sanjaya icon** to start it — it runs silently in the tray,
  no black console window.
- Click the tray eye → **Open Dashboard** to see your day. The dashboard opens in
  its **own clean window** (no browser tabs or address bar), so it looks and
  behaves like a normal desktop program.

Want it to start on its own every time you log in? In the dashboard go to
**Settings → About → Start with Windows** (or the tray menu), and tick it.

To remove the shortcuts later:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1 -Uninstall
```

> **Why a browser window and not a fully custom app?** The dashboard is shown
> through Edge/Chrome's built-in "app mode", which strips away all the browser
> chrome. This keeps Sanjaya featherweight and rock-solid — the part that matters
> (watching your time and keeping your data safe) is never affected by how the
> screens are drawn. It looks like an app; it can't break like a fragile one.

## Step 8 — Load the browser extension (recommended)

Sanjaya works from window titles alone, but a small helper extension makes web
tracking much sharper — exact search queries, real page URLs, and YouTube
channel names.

1. Open the file `extension\background.js` and set its `TOKEN` value to the **same**
   `SANJAYA_INGEST_TOKEN` you chose in Step 4.
2. In Edge or Chrome, go to `chrome://extensions` (or `edge://extensions`).
3. Turn on **Developer mode** (top-right toggle).
4. Click **Load unpacked** and pick the `extension` folder inside your Sanjaya
   project.

That's it — the extension quietly reports the active tab to Sanjaya. See
[`extension/README.md`](../extension/README.md) for details.

---

## Using Sanjaya day to day

- **The tray eye** is your remote control: Open Dashboard, Pause (stop tracking
  for a while — e.g. during a private task), Summarize now (write today's journal
  on demand), Start with Windows, and Quit.
- **Today** — your live day: focus score, timeline, category mix, the AI journal,
  highlights, and goal meters.
- **History / Insights** — past days and weekly trends.
- **Goals** — set targets like "≥3h Placements daily" and watch streaks.
- **Review** — quickly fix anything Sanjaya wasn't sure about; it learns your
  corrections.
- **Settings** — categories, rules, privacy (exclude apps/sites, redaction,
  retention), AI options, and data export (JSON / CSV / Markdown).

Anything wrong on a span or in the journal? Click it and fix it — Sanjaya
remembers the correction as a rule.

## Where your data lives

Everything is in the `data` folder inside your Sanjaya project
(`data\sanjaya.db`). Your `.env` and `config.toml` stay there too. None of it is
uploaded anywhere. Only short, privacy-filtered text summaries go to Groq to
write the journal — and you can exclude apps/sites so they never leave your PC at
all.

## Updating Sanjaya

From the project folder:

```powershell
git pull            # get the latest code (skip if you used a ZIP)
uv sync             # update dependencies
uv run python -m sanjaya --init-db   # apply any database changes (safe to re-run)
```

Then start it again from your Desktop icon.

---

## Troubleshooting

**I don't see the tray eye.** Click the "^" arrow near the clock — Windows often
hides new tray icons. Drag it out to keep it visible.

**"Open Dashboard" opens a normal browser tab, not an app window.** That happens
only if Edge/Chrome couldn't be found. Everything still works; install Edge or
Chrome for the clean window.

**The journal isn't being written.** Check your `GROQ_API_KEY` in `.env`, then use
**Settings → AI → Test connection**. If you were offline, the work is queued and
writes itself once you reconnect.

**Websites show only "chrome.exe" or generic titles.** Load the browser extension
(Step 8) and make sure its token matches your `.env`.

**Double-clicking the icon does nothing.** Re-run
`scripts\install_shortcut.ps1` after `uv sync`, so the shortcut points at the
installed environment. If you see a "No .venv found" message, run `uv sync` first.

**I want to start over.** Quit Sanjaya, delete the `data` folder, and run
`uv run python -m sanjaya --init-db` again. (This erases all recorded history.)

## Uninstalling

1. Quit Sanjaya from the tray.
2. Remove the shortcuts:
   `powershell -ExecutionPolicy Bypass -File scripts\install_shortcut.ps1 -Uninstall`
3. If autostart was on, untick **Start with Windows** first (or delete
   `Sanjaya.lnk` from your Startup folder).
4. Delete the whole `sanjaya` project folder.

---

Need the deep details? See [`README.md`](../README.md) for the developer view and
[`PRD.md`](../PRD.md) for the full product spec. For a thorough acceptance pass,
follow [`docs/qa-checklist.md`](qa-checklist.md).
