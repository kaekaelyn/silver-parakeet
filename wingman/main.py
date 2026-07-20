"""CLI entrypoint: `wingman serve` (default) and `wingman init-db`."""

import argparse
import logging
import sys

import uvicorn

from wingman import db
from wingman.backup import create_backup
from wingman.config import ConfigError, load_settings


def _setup_logging() -> None:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wingman")
    parser.set_defaults(reload=False)
    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser("serve", help="run the web app (default)")
    serve_parser.add_argument("--reload", action="store_true", help="auto-reload on code changes")
    subparsers.add_parser("init-db", help="create the database and apply migrations")
    backup_parser = subparsers.add_parser(
        "backup", help="write a tarball of the database and documents"
    )
    backup_parser.add_argument(
        "dest", nargs="?", default=None, help="destination directory (default: home)"
    )
    args = parser.parse_args(argv)

    _setup_logging()
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"wingman: configuration error: {exc}", file=sys.stderr)
        return 1

    if args.command == "init-db":
        with db.session(settings.db_path) as conn:
            applied = db.migrate(conn)
        print(
            f"database ready at {settings.db_path}"
            + (f" (applied: {', '.join(applied)})" if applied else " (up to date)")
        )
        return 0

    if args.command == "backup":
        out_path = create_backup(settings, args.dest)
        print(f"backup written to {out_path}")
        return 0

    uvicorn.run(
        "wingman.app:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        reload=args.reload,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
