// Sanjaya YouTube content script (PRD §8.8). Reports the current video's id,
// title, channel, play state and position to the background worker. Read-only —
// it never modifies the page and talks only to the extension's own worker.

(function () {
  function docTitle() {
    // Strip the "(N) " unread-count prefix and the " - YouTube" suffix.
    return document.title
      .replace(/^\(\d+\)\s*/, "")
      .replace(/\s*-\s*YouTube$/, "")
      .trim();
  }

  function ytDetail() {
    const params = new URLSearchParams(location.search);
    const video = document.querySelector("video");
    const channelEl = document.querySelector(
      "ytd-video-owner-renderer #channel-name a, #owner #channel-name a, " +
      "ytd-channel-name a, #upload-info a"
    );
    const titleEl = document.querySelector(
      "h1.ytd-watch-metadata yt-formatted-string, h1.ytd-watch-metadata, " +
      "#title h1 yt-formatted-string, h1.title yt-formatted-string"
    );
    const dt = docTitle();
    return {
      video_id: params.get("v"),
      title: (titleEl && titleEl.textContent.trim()) || dt || null,
      channel: channelEl ? channelEl.textContent.trim() : null,
      playing: video ? !video.paused : null,
      position: video ? Math.floor(video.currentTime) : null,
    };
  }

  let last = "";
  function report() {
    if (!/\/watch/.test(location.pathname)) return; // only real video pages
    const d = ytDetail();
    const key = JSON.stringify([d.video_id, d.title, d.channel, d.playing]);
    if (key === last) return; // dedupe: only send on meaningful change
    last = key;
    try {
      chrome.runtime.sendMessage({ type: "yt", data: d });
    } catch (e) {
      /* worker asleep; next tick retries */
    }
  }

  // Burst of early re-reads: the title/channel DOM lands a beat after load, so
  // poll quickly at first to catch it, then settle to a 5s heartbeat.
  function burst() {
    report();
    [800, 2000, 4000].forEach((ms) => setTimeout(report, ms));
  }
  burst();
  setInterval(report, 5000);
  // YouTube is an SPA — this fires on in-page navigations between videos.
  document.addEventListener("yt-navigate-finish", burst);
})();
