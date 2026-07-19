"""`wingman backup`: one tarball with a consistent DB snapshot + documents."""

import logging
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from wingman.config import Settings

logger = logging.getLogger(__name__)


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
