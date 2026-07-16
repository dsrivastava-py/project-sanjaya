// Sanjaya YouTube content script (PRD §8.8). Reports the current video's id,
// title, channel, play state and position to the background worker. Read-only —
// it never modifies the page and talks only to the extension's own worker.

(function () {
  function ytDetail() {
    const params = new URLSearchParams(location.search);
    const video = document.querySelector("video");
    const channelEl = document.querySelector(
      "#owner #channel-name a, ytd-channel-name a, #upload-info a"
    );
    const titleEl = document.querySelector(
      "h1.ytd-watch-metadata, h1.title yt-formatted-string"
    );
    return {
      video_id: params.get("v"),
      title:
        (titleEl && titleEl.textContent.trim()) ||
        document.title.replace(/ - YouTube$/, "").trim() ||
        null,
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

  report();
  setInterval(report, 5000);
  // YouTube is an SPA — this fires on in-page navigations between videos.
  document.addEventListener("yt-navigate-finish", report);
})();
