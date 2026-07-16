"""FastAPI application factory (PRD §5, §10.7). Localhost-only; serves the JSON
API under ``/api``, the browser-extension ingest endpoint at ``/ingest/browser``,
and — once the dashboard is built (Phase 6) — the static SPA at ``/``.

CORS stays off: the extension POSTs directly to ``127.0.0.1`` and the SPA is
served same-origin. Routers are registered before the static mount so ``/api``
and ``/ingest`` always win over the SPA catch-all.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import Config
from ..runtime import RuntimeState
from . import api, ingest

STATIC_DIR = Path(__file__).resolve().parent / "static"

_PLACEHOLDER = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Sanjaya</title><style>body{{background:#0A0D19;color:#F2F4FA;
font-family:system-ui,sans-serif;display:grid;place-items:center;height:100vh;
margin:0}}.c{{color:#E8B44A}}small{{color:#6E7691}}</style></head>
<body><div style="text-align:center"><h1><span class="c">Sanjaya</span> is running.</h1>
<p>Your day, witnessed. Your journal, written.</p>
<small>Dashboard SPA arrives in Phase 6. API live at <code>/api/status</code>.</small>
</div></body></html>"""


def create_app(cfg: Config, state: RuntimeState, controller=None) -> FastAPI:
    app = FastAPI(title="Sanjaya", version=__version__,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg = cfg
    app.state.rt = state
    app.state.controller = controller

    app.include_router(api.router)
    app.include_router(ingest.router)

    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        def _root() -> str:
            return _PLACEHOLDER

    return app
