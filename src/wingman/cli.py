from __future__ import annotations

import argparse

import uvicorn

from wingman.config import load_settings
from wingman.db.migrations import migrate


def main() -> None:
    parser = argparse.ArgumentParser(prog="wingman")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("init-db")
    subparsers.add_parser("serve")
    args = parser.parse_args()
    settings = load_settings()
    if args.command == "init-db":
        migrate(settings.database_path)
        print(f"Initialized {settings.database_path}")
    else:
        uvicorn.run("wingman.web.app:app", host=settings.host, port=settings.port)
