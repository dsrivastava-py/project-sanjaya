// Sanjaya browser extension — MV3 background service worker (PRD §8.8).
//
// Watches the active tab and forwards {ts,url,title,favicon_domain,audible,event}
// to the local Sanjaya server. YouTube tabs additionally carry video id/title/
// channel/state from the content script. Read-only; posts ONLY to 127.0.0.1.
//
// Shipped as plain JS so it loads unpacked with no build step (PRD §6). It uses
// no TypeScript-only syntax, so it doubles as the vanilla-TS source.

const ENDPOINT = "http://127.0.0.1:8756/ingest/browser";
// MUST match SANJAYA_INGEST_TOKEN in your .env. Edit this line after installing.
const TOKEN = "change-me-to-a-long-random-token";
const FLUSH_MS = 10000; // heartbeat POST cadence (PRD §8.8)

let current = null;      // latest active-tab snapshot
const ytByTab = {};      // tabId -> youtube detail from the content script

function domainOf(url) {
  try {
    const h = new URL(url).hostname.toLowerCase();
    return h.startsWith("www.") ? h.slice(4) : h;
  } catch (e) {
    return null;
  }
}

function nowTs() {
  return Math.floor(Date.now() / 1000);
}

function snapshot(tab, event) {
  if (!tab || !tab.url || !/^https?:/.test(tab.url)) return null; // ignore chrome://, file:// etc.
  const domain = domainOf(tab.url);
  const snap = {
    ts: nowTs(),
    url: tab.url,
    title: tab.title || null,
    favicon_domain: domain,
    audible: !!tab.audible,
    event: event || "update",
  };
  const yt = ytByTab[tab.id];
  if (yt && domain && domain.endsWith("youtube.com")) snap.youtube = yt;
  return snap;
}

async function post(snap) {
  if (!snap) return;
  try {
    await fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Sanjaya-Token": TOKEN },
      body: JSON.stringify(snap),
    });
  } catch (e) {
    // Server down / tracking paused — drop silently; the collector still
    // title-parses at lower fidelity (PRD §8.8).
  }
}

async function refresh(event, immediate) {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const snap = snapshot(tab, event);
  if (!snap) return;
  current = snap;
  if (immediate) post(snap);
}

chrome.tabs.onActivated.addListener(() => refresh("activated", true));
chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.url) refresh("navigation", true); // immediate on navigation
  else if (info.title || info.audible !== undefined) refresh("update", false);
});
chrome.windows.onFocusChanged.addListener((wid) => {
  if (wid !== chrome.windows.WINDOW_ID_NONE) refresh("focus", true);
});
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (msg && msg.type === "yt" && sender.tab) {
    ytByTab[sender.tab.id] = msg.data;
    // Immediate: YouTube fills in title/channel a beat AFTER the page loads, so
    // this update must POST now — not wait for the slow MV3 alarm, by which time
    // the span has closed with only the video_id (PRD §8.8).
    refresh("yt", true);
  }
});
chrome.tabs.onRemoved.addListener((tabId) => {
  delete ytByTab[tabId];
});

// MV3 service workers sleep; an alarm wakes us to POST the current tab every 10s.
chrome.alarms.create("flush", { periodInMinutes: FLUSH_MS / 60000 });
chrome.alarms.onAlarm.addListener((a) => {
  if (a.name === "flush") post(current);
});
