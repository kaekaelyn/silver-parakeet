import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

from wingman import backup, db, main
from wingman.config import Settings


def test_contact_details_roundtrip(client: TestClient) -> None:
    response = client.post(
        "/profile/contact",
        data={
            "contact.name": "Andy Example",
            "contact.email": "andy@example.com",
            "contact.github": "https://github.com/andy",
            "ignored.key": "should not be stored",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/profile").text
    assert "Andy Example" in page
    with db.session(client.app.state.settings.db_path) as conn:
        keys = {r["key"] for r in conn.execute("SELECT key FROM profile")}
    assert "contact.name" in keys
    assert "ignored.key" not in keys


def test_document_upload_default_and_delete(client: TestClient) -> None:
    settings = client.app.state.settings
    first = client.post(
        "/profile/documents",
        files={"file": ("resume-v1.pdf", b"%PDF-1.4 first", "application/pdf")},
        data={"kind": "resume", "name": "Resume v1"},
        follow_redirects=False,
    )
    assert first.status_code == 303
    client.post(
        "/profile/documents",
        files={"file": ("resume-v2.pdf", b"%PDF-1.4 second", "application/pdf")},
        data={"kind": "resume", "name": "Resume v2"},
    )
    with db.session(settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY id").fetchall()
    assert [r["is_default"] for r in rows] == [1, 0]  # first upload is default
    assert Path(rows[0]["path"]).read_bytes() == b"%PDF-1.4 first"

    client.post(f"/profile/documents/{rows[1]['id']}/default")
    with db.session(settings.db_path) as conn:
        defaults = {
            r["id"]: r["is_default"] for r in conn.execute("SELECT id, is_default FROM documents")
        }
    assert defaults[rows[0]["id"]] == 0 and defaults[rows[1]["id"]] == 1

    # Deleting the default promotes the remaining document.
    client.post(f"/profile/documents/{rows[1]['id']}/delete")
    with db.session(settings.db_path) as conn:
        remaining = conn.execute("SELECT * FROM documents").fetchall()
    assert len(remaining) == 1
    assert remaining[0]["is_default"] == 1
    assert not Path(rows[1]["path"]).exists()


def test_answers_crud(client: TestClient) -> None:
    client.post(
        "/profile/answers",
        data={"question_pattern": "notice period", "answer": "Two weeks", "kind": "text"},
    )
    page = client.get("/profile").text
    assert "notice period" in page
    with db.session(client.app.state.settings.db_path) as conn:
        answer_id = conn.execute("SELECT id FROM answers").fetchone()["id"]
    client.post(f"/profile/answers/{answer_id}/delete")
    assert "notice period" not in client.get("/profile").text


def test_cover_letter_template_saved(client: TestClient) -> None:
    client.post(
        "/profile/cover-letter",
        data={"template_text": "Dear {company}, I admire your work on..."},
    )
    assert "I admire your work" in client.get("/profile").text


def test_backup_cli_produces_tarball(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    with db.session(settings.db_path) as conn:
        db.migrate(conn)
    settings.documents_dir.mkdir(parents=True)
    (settings.documents_dir / "resume.pdf").write_bytes(b"%PDF fake")

    out = backup.create_backup(settings, tmp_path / "backups")
    assert out.exists()
    with tarfile.open(out) as tar:
        names = tar.getnames()
    assert "wingman.db" in names
    assert "documents/resume.pdf" in names


def test_backup_via_cli_entrypoint(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    monkeypatch.setenv("WINGMAN_DATA_DIR", str(data_dir))
    with db.session(data_dir / "wingman.db") as conn:
        db.migrate(conn)
    exit_code = main.main(["backup", str(tmp_path / "out")])
    assert exit_code == 0
    assert list((tmp_path / "out").glob("wingman-backup-*.tar.gz"))
