"""Canonical filesystem locations. Everything Sanjaya writes lives under ``data/``
next to the repo root so the app is fully self-contained and trivially portable.
"""
from __future__ import annotations

from pathlib import Path

# repo root = parent of the ``sanjaya`` package directory
ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"
EXPORT_DIR = DATA_DIR / "exports"
AI_PAYLOAD_DIR = DATA_DIR / "ai_payloads"

DB_PATH = DATA_DIR / "sanjaya.db"
CONFIG_PATH = ROOT / "config.toml"
ENV_PATH = ROOT / ".env"


def ensure_dirs() -> None:
    """Create the runtime directories if missing. Cheap; safe to call often."""
    for d in (DATA_DIR, LOG_DIR, EXPORT_DIR, AI_PAYLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)
