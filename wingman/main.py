"""CLI entrypoint: `wingman serve` (default) and `wingman init-db`."""

import argparse
import logging
import sys

import uvicorn

from wingman import db
from wingman.config import load_settings


def _setup_logging() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wingman")
    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser("serve", help="run the web app (default)")
    serve_parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    subparsers.add_parser("init-db", help="create the database and apply migrations")
    args = parser.parse_args(argv)

    _setup_logging()
    settings = load_settings()

    if args.command == "init-db":
        conn = db.connect(settings.db_path)
        try:
            applied = db.migrate(conn)
        finally:
            conn.close()
        print(
            f"database ready at {settings.db_path}"
            + (f" (applied: {', '.join(applied)})" if applied else " (up to date)")
        )
        return 0

    uvicorn.run(
        "wingman.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=getattr(args, "reload", False),
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
