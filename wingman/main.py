"""CLI entrypoint: `wingman serve` (default), `init-db`, `backup`, `restore`."""

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from wingman import db
from wingman.backup import RestoreError, create_backup, restore_backup
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
    restore_parser = subparsers.add_parser(
        "restore", help="restore a backup tarball (database + documents)"
    )
    restore_parser.add_argument("tarball", help="path to a wingman-backup-*.tar.gz")
    restore_parser.add_argument(
        "--force",
        action="store_true",
        help="replace the existing database (a safety backup is written first)",
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

    if args.command == "restore":
        try:
            for line in restore_backup(settings, Path(args.tarball), force=args.force):
                print(line)
        except RestoreError as exc:
            print(f"wingman: restore refused: {exc}", file=sys.stderr)
            return 1
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
