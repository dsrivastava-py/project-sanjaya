<div align="center">

# 👁️ Sanjaya browser extension

**High-fidelity web signals for your local Sanjaya journal.**

</div>

Window titles alone can't tell a coding tutorial from a music video. This tiny MV3
extension gives Sanjaya the details that matter — **exact URLs, search queries, and
YouTube video title / channel / play-state** (PRD §8.8).

**Local-only.** It POSTs **only** to `http://127.0.0.1:8756`. No page content, no
keystrokes, no browsing history — just the active tab.

---

## Install (Chrome / Edge, unpacked)

1. **Set your shared secret.** Open `background.js` and replace the `TOKEN` value with
   the same string you put in the repo `.env` as `SANJAYA_INGEST_TOKEN`.
2. Go to `chrome://extensions` (or `edge://extensions`).
3. Enable **Developer mode** (top-right).
4. **Load unpacked** → select this `extension/` folder.
5. Make sure Sanjaya is running. The dashboard **Settings → About** page shows
   *extension last-seen* once events flow.

> Changed the token later? Hit the **↻ reload** icon on the extension card — unpacked
> extensions don't auto-update.

---

## What it sends

```jsonc
{
  "ts": 1720000000,
  "url": "https://…",
  "title": "…",
  "favicon_domain": "example.com",
  "audible": false,
  "event": "navigation",
  "youtube": {                 // only on youtube.com/watch
    "video_id": "…",
    "title": "…",
    "channel": "…",
    "playing": true,
    "position": 42
  }
}
```

It posts immediately on tab switch / navigation, and heartbeats the active tab
periodically. YouTube detail is read from the page and sent the moment the title and
channel render.

---

## Privacy

- **Incognito windows are not tracked** unless you explicitly enable the extension in
  incognito — the intended escape hatch.
- If the extension is off or the browser is closed, Sanjaya falls back to window-title
  parsing; everything still works at lower fidelity.

---

## Notes

- Plain JS — loads unpacked with **no build step**. No TypeScript-only syntax, so the
  files double as the vanilla-TS source.
- `host_permissions` is scoped to `127.0.0.1:8756` only.
