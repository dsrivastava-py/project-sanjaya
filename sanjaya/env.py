"""Secret loading from ``.env`` (PRD §9.1, §8.8). Values are read live from the
process environment so tests can inject them; the ``.env`` file is loaded once
and never overrides an already-set variable. The secrets themselves are never
logged.
"""
from __future__ import annotations

import os

from . import paths

_loaded = False


def _ensure() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        from dotenv import load_dotenv
    except Exception:  # noqa: BLE001 - dotenv optional at runtime
        return
    if paths.ENV_PATH.exists():
        load_dotenv(paths.ENV_PATH, override=False)


def get(name: str, default: str | None = None) -> str | None:
    _ensure()
    return os.getenv(name, default)


def groq_api_key() -> str | None:
    return get("GROQ_API_KEY")


def ingest_token() -> str | None:
    return get("SANJAYA_INGEST_TOKEN")
