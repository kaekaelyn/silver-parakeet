from fastapi.testclient import TestClient


def test_inbox_loads(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Inbox" in response.text


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["migrations"] >= 1


def test_startup_records_event(client: TestClient) -> None:
    from wingman import db

    settings = client.app.state.settings
    conn = db.connect(settings.db_path)
    kinds = [row["kind"] for row in conn.execute("SELECT kind FROM events")]
    conn.close()
    assert "app.started" in kinds


def test_static_css_served(client: TestClient) -> None:
    response = client.get("/static/wingman.css")
    assert response.status_code == 200
