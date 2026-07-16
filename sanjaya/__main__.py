"""Entry point: ``python -m sanjaya``.

Light commands (``--version``, ``--init-db``) never import the Windows-only
collector/tray modules, so they run anywhere and stay fast. The default action
boots the full app (collector + tray + server), which is Windows-specific.
"""
from __future__ import annotations

import argparse
import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sanjaya", description="Sanjaya activity journal")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    parser.add_argument("--init-db", action="store_true", help="create/migrate the database and exit")
    args = parser.parse_args(argv)

    if args.version:
        print(f"sanjaya {__version__}")
        return 0

    if args.init_db:
        from . import db
        path = db.init_db()
        print(f"database ready: {path}")
        return 0

    # Default: run the app. Imported lazily so light commands avoid heavy deps.
    from .app import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
