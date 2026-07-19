from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from wingman.sources import ADAPTERS, RawPosting, SourceAdapter


class _StubSource(SourceAdapter):
    kind = "remotive"
    default_name = "Remotive"

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        return [
            RawPosting(url="https://example.com/stub/1", title="Stub Engineer", company="Stub Co")
        ]


def test_sources_page_lists_defaults(client: TestClient) -> None:
    response = client.get("/sources")
    assert response.status_code == 200
    for name in ("Remotive", "RemoteOK", "We Work Remotely", "HN Who is hiring?"):
        assert name in response.text


def test_toggle_source(client: TestClient) -> None:
    from wingman import db

    settings = client.app.state.settings
    response = client.post("/sources/1/toggle", follow_redirects=False)
    assert response.status_code == 303
    with db.session(settings.db_path) as conn:
        assert conn.execute("SELECT enabled FROM sources WHERE id = 1").fetchone()[0] == 0
    client.post("/sources/1/toggle")
    with db.session(settings.db_path) as conn:
        assert conn.execute("SELECT enabled FROM sources WHERE id = 1").fetchone()[0] == 1


def test_fetch_now_ingests_jobs(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(ADAPTERS, "remotive", _StubSource())
    response = client.post("/sources/1/fetch", follow_redirects=False)
    assert response.status_code == 303
    page = client.get("/sources")
    assert "Stub" not in page.text  # job title not shown here, but count is
    assert client.get("/").text.count("Wingman is running")  # dashboard still healthy
    from wingman import db

    with db.session(client.app.state.settings.db_path) as conn:
        row = conn.execute("SELECT title, company FROM jobs").fetchone()
    assert row["title"] == "Stub Engineer"
    assert row["company"] == "Stub Co"


def test_add_rss_source(client: TestClient) -> None:
    response = client.post(
        "/sources/add-rss",
        data={"name": "Django jobs", "feed_url": "https://djangojobs.example/feed.rss"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/sources")
    assert "Django jobs" in page.text
