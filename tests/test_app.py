from __future__ import annotations

from fastapi.testclient import TestClient

from wingman.web.app import create_app


def test_health() -> None:
    client = TestClient(create_app())
    assert client.get("/health").json() == {"status": "ok"}


def test_dashboard_names_andy_persons() -> None:
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    assert "Andy Persons" in response.text
