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
    from wingman import db

    with db.session(client.app.state.settings.db_path) as conn:
        row = conn.execute("SELECT title, company FROM jobs").fetchone()
    assert row["title"] == "Stub Engineer"
    assert row["company"] == "Stub Co"
    # The fetched job was scored on ingest and shows up in the inbox.
    assert "Stub Engineer" in client.get("/").text


def test_fetch_all_now_refreshes_enabled_sources(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ADAPTERS, "remotive", _StubSource())
    # Keep the test offline: disable the other seeded boards so only the
    # stubbed Remotive is polled by the refresh-all pass.
    for source_id in (2, 3, 4):
        client.post(f"/sources/{source_id}/toggle")

    response = client.post("/sources/fetch-all", follow_redirects=False)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/sources?refreshed=1")
    assert "new=1" in location and "errors=0" in location

    # The pulled job is ingested and scored, and the summary banner renders.
    assert "Stub Engineer" in client.get("/").text
    assert "Refreshed 1 source" in client.get(location).text

    from wingman import db

    with db.session(client.app.state.settings.db_path) as conn:
        kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "fetch.all" in kinds


def test_add_rss_source(client: TestClient) -> None:
    response = client.post(
        "/sources/add-rss",
        data={"name": "Django jobs", "feed_url": "https://djangojobs.example/feed.rss"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/sources")
    assert "Django jobs" in page.text


def test_delete_rss_source_keeps_builtins(client: TestClient) -> None:
    from wingman import db

    client.post("/sources/add-rss", data={"name": "Typo feed", "feed_url": "https://x.example/f"})
    page = client.get("/sources").text
    assert "Typo feed" in page
    settings = client.app.state.settings
    with db.session(settings.db_path) as conn:
        rss_id = conn.execute("SELECT id FROM sources WHERE name = 'Typo feed'").fetchone()["id"]
    response = client.post(f"/sources/{rss_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert "Typo feed" not in client.get("/sources").text
    # Built-in boards refuse deletion.
    client.post("/sources/1/delete")
    assert "Remotive" in client.get("/sources").text
    with db.session(settings.db_path) as conn:
        kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events ORDER BY id")]
    assert "source.added" in kinds and "source.deleted" in kinds


def test_add_and_delete_watchlist_source(client: TestClient) -> None:
    response = client.post(
        "/sources/add-watchlist",
        data={"company_name": "Stripe", "ats": "greenhouse", "slug": "stripe"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/sources").text
    assert "Watchlist: Stripe" in page

    # A pasted board URL still yields the slug.
    client.post(
        "/sources/add-watchlist",
        data={
            "company_name": "Linear",
            "ats": "ashby",
            "slug": "https://jobs.ashbyhq.com/linear/",
        },
        follow_redirects=False,
    )
    import json as _json

    from wingman import db as _db

    settings = client.app.state.settings
    with _db.session(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM sources WHERE name = 'Watchlist: Linear'").fetchone()
        assert _json.loads(row["config_json"])["company"] == "linear"
        watch_id = conn.execute(
            "SELECT id FROM sources WHERE name = 'Watchlist: Stripe'"
        ).fetchone()["id"]

    # Watchlist sources are deletable; unknown ATS kinds are rejected.
    client.post(f"/sources/{watch_id}/delete", follow_redirects=False)
    assert "Watchlist: Stripe" not in client.get("/sources").text
    client.post(
        "/sources/add-watchlist",
        data={"company_name": "X", "ats": "workday", "slug": "x"},
        follow_redirects=False,
    )
    assert "Watchlist: X" not in client.get("/sources").text


def test_keyed_boards_hidden_until_keys_entered(client: TestClient) -> None:
    page = client.get("/sources").text
    assert "not configured" in page  # the key-entry section shows
    # No Adzuna/USAJOBS source rows exist yet.
    assert "sources/keys" in page

    client.post(
        "/sources/keys",
        data={"kind": "adzuna", "app_id": "id1", "app_key": "k1", "search": "python"},
        follow_redirects=False,
    )
    page = client.get("/sources").text
    assert ">Adzuna</" in page or "Adzuna</strong>" in page  # now in the table

    # Saving search terms with blank key fields keeps the stored keys.
    client.post(
        "/sources/keys",
        data={"kind": "adzuna", "app_id": "", "app_key": "", "search": "golang"},
        follow_redirects=False,
    )
    from wingman import boardkeys
    from wingman import db as _db

    settings = client.app.state.settings
    with _db.session(settings.db_path) as conn:
        assert boardkeys.board_keys(conn, "adzuna") == {"app_id": "id1", "app_key": "k1"}
        row = conn.execute("SELECT config_json FROM sources WHERE kind = 'adzuna'").fetchone()
        assert "golang" in row["config_json"]

    # Removing keys hides the source again and disables polling.
    client.post("/sources/keys/clear", data={"kind": "adzuna"}, follow_redirects=False)
    with _db.session(settings.db_path) as conn:
        assert boardkeys.keys_present(conn, "adzuna") is False
        row = conn.execute("SELECT enabled FROM sources WHERE kind = 'adzuna'").fetchone()
        assert row["enabled"] == 0
    assert "Adzuna</strong> —" in client.get("/sources").text  # keys section remains
