"""Events page (M7c): rendering, kind-prefix filter, pagination, fallback."""

from fastapi.testclient import TestClient

from wingman import db
from wingman.config import Settings
from wingman.routes.events import PAGE_SIZE, pretty_payload


def _record(settings: Settings, kind: str, payload_json: str | None = None, times: int = 1) -> None:
    with db.session(settings.db_path) as conn:
        for _ in range(times):
            conn.execute(
                "INSERT INTO events (kind, payload_json) VALUES (?, ?)", (kind, payload_json)
            )
        conn.commit()


def test_events_page_renders_newest_first(client: TestClient, settings: Settings) -> None:
    _record(settings, "fetch.ok", '{"source": "Remotive", "jobs": 3}')
    _record(settings, "capture.ok")
    page = client.get("/events")
    assert page.status_code == 200
    assert "fetch.ok" in page.text and "capture.ok" in page.text
    # capture.ok was recorded last, so it must appear first.
    assert page.text.index("capture.ok") < page.text.index("fetch.ok")
    # Payload JSON is pretty-printed inside a <details> block.
    assert "<details>" in page.text
    assert "&#34;source&#34;: &#34;Remotive&#34;" in page.text


def test_kind_prefix_filter(client: TestClient, settings: Settings) -> None:
    _record(settings, "fetch.ok")
    _record(settings, "apply.submitted")
    page = client.get("/events", params={"kind": "apply."})
    assert "apply.submitted" in page.text
    assert "fetch.ok" not in page.text


def test_unknown_kind_prefix_falls_back_to_all(client: TestClient, settings: Settings) -> None:
    _record(settings, "fetch.ok")
    _record(settings, "apply.submitted")
    page = client.get("/events", params={"kind": "bogus."})
    assert page.status_code == 200
    assert "fetch.ok" in page.text and "apply.submitted" in page.text


def test_filter_is_a_prefix_not_a_pattern(client: TestClient, settings: Settings) -> None:
    _record(settings, "notify.sent")
    _record(settings, "renotify.sent")  # would match '%notify.%', must not match prefix
    page = client.get("/events", params={"kind": "notify."})
    assert "notify.sent" in page.text
    assert "renotify.sent" not in page.text


def test_pagination_pages(client: TestClient, settings: Settings) -> None:
    _record(settings, "fetch.ok", times=PAGE_SIZE + 5)
    first = client.get("/events")
    assert first.text.count("fetch.ok") == PAGE_SIZE
    assert f"offset={PAGE_SIZE}" in first.text  # Older link present
    assert "Newer" not in first.text
    second = client.get("/events", params={"offset": PAGE_SIZE})
    # app.started from startup + 5 overflow rows land on page two.
    assert "fetch.ok" in second.text
    assert "Newer" in second.text
    assert "Older" not in second.text


def test_pretty_payload_handles_garbage() -> None:
    assert pretty_payload(None) == ""
    assert pretty_payload("not json") == "not json"
    assert pretty_payload('{"b": 1, "a": 2}') == '{\n  "a": 2,\n  "b": 1\n}'


def test_nav_links_log(client: TestClient) -> None:
    page = client.get("/metrics")
    assert '<a href="/events">Log</a>' in page.text
