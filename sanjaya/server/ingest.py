"""Browser-extension ingest endpoint (PRD §8.8, §10.7).

The extension POSTs tab/YouTube events here every 10s (or immediately on
navigation) with an ``X-Sanjaya-Token`` header. We authenticate the token,
then record the newest event into the shared :class:`RuntimeState` so the
collector can *upgrade* the matching foreground browser span (±3s window). No
span is written here — the collector owns span creation (thread affinity).
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel

from .. import env
from ..collector import parsers
from ..log import get
from ..runtime import ExtEvent
from ..timeutil import now_ts

router = APIRouter()
_log = get("server.ingest")


class YouTube(BaseModel):
    video_id: str | None = None
    title: str | None = None
    channel: str | None = None
    playing: bool | None = None
    position: float | None = None


class BrowserEvent(BaseModel):
    ts: int | None = None
    url: str | None = None
    title: str | None = None
    favicon_domain: str | None = None
    audible: bool | None = None
    event: str | None = None
    youtube: YouTube | None = None


class IngestBody(BaseModel):
    """Accepts either a batch ``{"events":[...]}`` or a single flat event."""
    events: list[BrowserEvent] | None = None
    ts: int | None = None
    url: str | None = None
    title: str | None = None
    favicon_domain: str | None = None
    audible: bool | None = None
    event: str | None = None
    youtube: YouTube | None = None


def _yt_detail(yt: YouTube | None) -> dict:
    detail: dict = {}
    if yt is None:
        return detail
    if yt.video_id:
        detail["video_id"] = yt.video_id
    if yt.title:
        detail["video_title"] = yt.title
    if yt.channel:
        detail["channel"] = yt.channel
    if yt.playing is not None:
        detail["playing"] = bool(yt.playing)
    if yt.position is not None:
        detail["position"] = yt.position
    return detail


@router.post("/ingest/browser")
def ingest_browser(
    body: IngestBody,
    request: Request,
    x_sanjaya_token: str | None = Header(default=None),
):
    expected = env.ingest_token()
    if not expected or x_sanjaya_token != expected:
        raise HTTPException(status_code=401, detail="invalid or missing ingest token")

    events = list(body.events or [])
    if not events and (body.url or body.title or body.youtube):
        events = [BrowserEvent(
            ts=body.ts, url=body.url, title=body.title,
            favicon_domain=body.favicon_domain, audible=body.audible,
            event=body.event, youtube=body.youtube,
        )]

    rt = request.app.state.rt
    accepted = 0
    for ev in events:
        ts = int(ev.ts) if ev.ts else now_ts()
        domain = ev.favicon_domain or parsers.domain_from_url(ev.url)
        rt.record_ext_event(ExtEvent(
            ts=ts, url=ev.url, title=ev.title, domain=domain,
            audible=bool(ev.audible), event=ev.event,
            detail=_yt_detail(ev.youtube),
        ))
        accepted += 1

    return {"accepted": accepted, "last_seen_ts": rt.last_ext_ts}
