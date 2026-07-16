# Sanjaya browser extension (MV3)

Gives Sanjaya high-fidelity web signals — exact URLs, search queries, and
YouTube video title/channel/state — that a window title alone can't provide
(PRD §8.8). Local-only: it POSTs **only** to `http://127.0.0.1:8756`.

## Install (Chrome / Edge, unpacked)

1. Set your shared secret. Open `background.js` and replace the `TOKEN` value
   with the same string you put in the repo `.env` as `SANJAYA_INGEST_TOKEN`.
2. Go to `chrome://extensions` (or `edge://extensions`).
3. Enable **Developer mode** (top-right).
4. **Load unpacked** → select this `extension/` folder.
5. Make sure Sanjaya is running (`./scripts/dev.ps1 run`). The dashboard
   **About** page shows *extension last-seen* once events flow.

## What it sends

`{ ts, url, title, favicon_domain, audible, event, youtube? }` where `youtube`
is `{ video_id, title, channel, playing, position }`. No page content, no
keystrokes, no history — just the active tab.

## Privacy

- Incognito windows are **not** tracked unless you explicitly enable the
  extension in incognito — this is the intended privacy escape hatch (§8.8).
- If the extension is off or the browser is closed, Sanjaya falls back to
  window-title parsing; everything still works at lower fidelity.

## Notes

- Files are plain JS so they load unpacked with no build step (PRD §6). They use
  no TypeScript-only syntax, so they also serve as the vanilla-TS source.
