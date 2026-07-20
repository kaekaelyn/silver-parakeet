"""`wingman restore`: round-trip, refusal without --force, hostile tarballs."""

import io
import shutil
import tarfile
from pathlib import Path

import pytest

from wingman import backup, db, main
from wingman.backup import RestoreError
from wingman.config import Settings


def _prepared_settings(tmp_path: Path, marker: str) -> Settings:
    """A data dir with a migrated DB carrying a marker row + one document."""
    settings = Settings(data_dir=tmp_path / "data")
    with db.session(settings.db_path) as conn:
        db.migrate(conn)
        _set_marker(conn, marker)
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    (settings.documents_dir / "resume.pdf").write_bytes(b"%PDF " + marker.encode())
    return settings


def _set_marker(conn, marker: str) -> None:
    conn.execute(
        """INSERT INTO profile (key, value) VALUES ('restore.marker', ?)
           ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
        (marker,),
    )
    conn.commit()


def _marker(settings: Settings) -> str | None:
    with db.session(settings.db_path) as conn:
        row = conn.execute("SELECT value FROM profile WHERE key = 'restore.marker'").fetchone()
        return row["value"] if row else None


def _tar_of_members(path: Path, names: list[str]) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name in names:
            info = tarfile.TarInfo(name)
            data = b"evil"
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_round_trip_backup_wipe_restore(tmp_path: Path) -> None:
    settings = _prepared_settings(tmp_path, "original")
    tarball = backup.create_backup(settings, tmp_path / "backups")

    shutil.rmtree(settings.data_dir)  # the disaster
    actions = backup.restore_backup(settings, tarball)

    assert _marker(settings) == "original"
    assert (settings.documents_dir / "resume.pdf").read_bytes() == b"%PDF original"
    assert any("database restored" in line for line in actions)
    assert any("documents restored" in line for line in actions)


def test_restore_refuses_existing_db_without_force(tmp_path: Path) -> None:
    settings = _prepared_settings(tmp_path, "precious")
    tarball = backup.create_backup(settings, tmp_path / "backups")
    with pytest.raises(RestoreError, match="--force"):
        backup.restore_backup(settings, tarball)
    assert _marker(settings) == "precious"  # nothing was touched


def test_force_restore_writes_safety_backup_then_swaps(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))

    settings = _prepared_settings(tmp_path, "old")
    tarball = backup.create_backup(settings, tmp_path / "backups")
    with db.session(settings.db_path) as conn:
        _set_marker(conn, "new")

    actions = backup.restore_backup(settings, tarball, force=True)

    assert _marker(settings) == "old"  # the backup's state is back
    safety = list(home.glob("wingman-backup-*.tar.gz"))
    assert len(safety) == 1
    assert any("safety backup" in line for line in actions)
    # The safety backup holds the pre-restore state, in case --force was a mistake.
    with tarfile.open(safety[0]) as tar:
        assert "wingman.db" in tar.getnames()


@pytest.mark.parametrize("hostile", ["../evil.db", "/abs/evil.db"])
def test_hostile_member_paths_are_rejected(tmp_path: Path, hostile: str) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    tarball = _tar_of_members(tmp_path / "hostile.tar.gz", [hostile, "wingman.db"])
    with pytest.raises(RestoreError, match="tarball member"):
        backup.restore_backup(settings, tarball)
    assert not settings.db_path.exists()  # nothing extracted, nothing swapped


def test_symlink_member_is_rejected(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    tarball = tmp_path / "link.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        info = tarfile.TarInfo("wingman.db")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    with pytest.raises(RestoreError, match="link"):
        backup.restore_backup(settings, tarball)


def test_tarball_without_db_is_rejected(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    tarball = _tar_of_members(tmp_path / "nodb.tar.gz", ["documents/resume.pdf"])
    with pytest.raises(RestoreError, match="not a Wingman backup"):
        backup.restore_backup(settings, tarball)


def test_unreadable_file_is_a_clean_refusal(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    not_a_tar = tmp_path / "garbage.tar.gz"
    not_a_tar.write_bytes(b"this is not a tarball")
    with pytest.raises(RestoreError, match="cannot read"):
        backup.restore_backup(settings, not_a_tar)
    with pytest.raises(RestoreError, match="no such file"):
        backup.restore_backup(settings, tmp_path / "missing.tar.gz")


def test_restore_via_cli_entrypoint(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("WINGMAN_DATA_DIR", str(tmp_path / "data"))
    settings = _prepared_settings(tmp_path, "cli")
    tarball = backup.create_backup(settings, tmp_path / "backups")

    assert main.main(["restore", str(tarball)]) == 1  # refused: DB exists
    assert main.main(["restore", str(tarball), "--force"]) == 0
    assert _marker(settings) == "cli"
