"""`wingman backup` / `wingman restore`: DB snapshot + documents, in and out.

Backup writes one tarball (consistent sqlite snapshot + the documents dir).
Restore validates the tarball hard before touching anything — no absolute
paths, no "..", no links — refuses to replace an existing database unless
forced, and when forced writes a safety backup first.
"""

import logging
import shutil
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from wingman.config import Settings

logger = logging.getLogger(__name__)


class RestoreError(Exception):
    """A restore that must not proceed; the message says why."""


def create_backup(settings: Settings, dest_dir: Path | None = None) -> Path:
    dest_dir = Path(dest_dir) if dest_dir else Path.home()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = dest_dir / f"wingman-backup-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / "wingman.db"
        # sqlite's backup API gives a consistent snapshot even mid-write.
        source = sqlite3.connect(settings.db_path)
        try:
            target = sqlite3.connect(snapshot)
            with target:
                source.backup(target)
            target.close()
        finally:
            source.close()
        with tarfile.open(out_path, "w:gz") as tar:
            tar.add(snapshot, arcname="wingman.db")
            if settings.documents_dir.is_dir():
                tar.add(settings.documents_dir, arcname="documents")
    logger.info("backup written to %s", out_path)
    return out_path


def _validated_members(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Reject hostile members before anything is extracted."""
    members = tar.getmembers()
    for member in members:
        parts = Path(member.name).parts
        if Path(member.name).is_absolute() or member.name.startswith(("/", "\\")):
            raise RestoreError(f"tarball member has an absolute path: {member.name!r}")
        if ".." in parts:
            raise RestoreError(f"tarball member escapes the extract dir: {member.name!r}")
        if member.issym() or member.islnk():
            raise RestoreError(f"tarball member is a link: {member.name!r}")
        if not (member.isfile() or member.isdir()):
            raise RestoreError(f"tarball member is not a plain file: {member.name!r}")
    if not any(m.name == "wingman.db" and m.isfile() for m in members):
        raise RestoreError("tarball has no wingman.db — not a Wingman backup")
    return members


def restore_backup(settings: Settings, tarball: Path, force: bool = False) -> list[str]:
    """Restore a `wingman backup` tarball. Returns the lines to print.

    Raises RestoreError instead of doing anything surprising: bad tarball,
    or an existing database without force.
    """
    tarball = Path(tarball)
    if not tarball.is_file():
        raise RestoreError(f"no such file: {tarball}")
    db_path = settings.db_path
    if db_path.exists() and not force:
        raise RestoreError(
            f"a database already exists at {db_path}; re-run with --force to replace it"
            " (a safety backup is written first)"
        )

    actions: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with tarfile.open(tarball) as tar:
                members = _validated_members(tar)
                tar.extractall(tmp, members=members)
        except tarfile.TarError as exc:
            raise RestoreError(f"cannot read {tarball}: {exc}") from exc

        if db_path.exists():
            safety = create_backup(settings)
            actions.append(f"safety backup of the current data written to {safety}")

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        for sidecar in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            sidecar.unlink(missing_ok=True)
        shutil.move(Path(tmp) / "wingman.db", db_path)
        actions.append(f"database restored to {db_path}")

        restored_docs = Path(tmp) / "documents"
        if restored_docs.is_dir():
            if settings.documents_dir.is_dir():
                shutil.rmtree(settings.documents_dir)
            shutil.move(restored_docs, settings.documents_dir)
            n_docs = sum(1 for p in settings.documents_dir.rglob("*") if p.is_file())
            actions.append(f"documents restored to {settings.documents_dir} ({n_docs} file(s))")
        else:
            actions.append("no documents in this backup; documents dir left as-is")

    for line in actions:
        logger.info("restore: %s", line)
    return actions
