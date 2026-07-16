"""Shared pytest fixtures. Tests here are cross-platform: they exercise the pure
logic (parsers, rules, focus, schema) and never touch Windows APIs or the live
Groq endpoint.
"""
from __future__ import annotations

import pytest

from sanjaya import db as dbmod


@pytest.fixture()
def db(tmp_path):
    """A fresh, migrated, seeded database in a temp dir."""
    path = tmp_path / "test.db"
    conn = dbmod.connect(path)
    dbmod.migrate(conn)
    yield conn
    conn.close()
