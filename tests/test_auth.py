"""M7a PIN gate: gate off = open app; gate on = cookie or /login.

TestClient's default client host is "testclient" — non-loopback, so it
exercises the gate whenever a PIN is set.
"""

import json
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wingman import auth, db
from wingman.app import create_app
from wingman.config import Settings

PIN = "4321"


@pytest.fixture
def pin_settings(tmp_path: Path, settings: Settings) -> Settings:
    return settings.model_copy(update={"pin": PIN})


@pytest.fixture
def pin_client(pin_settings: Settings) -> Iterator[TestClient]:
    app = create_app(pin_settings, with_scheduler=False)
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Neutralize the brute-force brake, recording that it was applied."""
    slept: list[float] = []
    monkeypatch.setattr("wingman.routes.auth.time.sleep", slept.append)
    return slept


def login(client: TestClient, pin: str = PIN, next_url: str = "/"):
    return client.post("/login", data={"pin": pin, "next": next_url})


def failed_events(settings: Settings) -> list[dict]:
    conn = db.connect(settings.db_path)
    try:
        rows = conn.execute("SELECT payload_json FROM events WHERE kind = 'auth.failed'")
        return [json.loads(row["payload_json"]) for row in rows.fetchall()]
    finally:
        conn.close()


def test_gate_off_everything_open(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/profile").status_code == 200
    assert client.get("/login").status_code == 404  # route only exists with a PIN


def test_gate_on_redirects_non_local_to_login(pin_client: TestClient) -> None:
    response = pin_client.get("/profile")
    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/profile"


def test_loopback_is_exempt(pin_settings: Settings) -> None:
    app = create_app(pin_settings, with_scheduler=False)
    with TestClient(app, client=("127.0.0.1", 50000)) as local_client:
        assert local_client.get("/").status_code == 200


def test_login_static_and_sw_reachable_pre_auth(pin_client: TestClient) -> None:
    for path in ("/login", "/static/wingman.css", "/static/manifest.webmanifest", "/sw.js"):
        assert pin_client.get(path).status_code == 200, path


def test_wrong_pin_reprompts_brakes_and_records_event(
    pin_client: TestClient, pin_settings: Settings, no_sleep: list[float]
) -> None:
    response = login(pin_client, pin="9999")
    assert response.status_code == 200
    assert "Wrong PIN" in response.text
    assert no_sleep == [1]
    events = failed_events(pin_settings)
    assert events == [{"ip": "testclient"}]
    assert PIN not in response.text


def test_right_pin_sets_cookie_and_unlocks_everything(pin_client: TestClient) -> None:
    response = login(pin_client, next_url="/profile")
    assert response.status_code == 303
    assert response.headers["location"] == "/profile"
    set_cookie = response.headers["set-cookie"]
    assert auth.COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie and "SameSite=lax" in set_cookie.replace("Lax", "lax")
    for path in ("/", "/profile", "/tracker", "/sources", "/metrics"):
        assert pin_client.get(path).status_code == 200, path


def test_forged_cookie_is_rejected(pin_client: TestClient) -> None:
    pin_client.cookies.set(auth.COOKIE_NAME, "0" * 64)
    assert pin_client.get("/").status_code == 303


def test_offsite_next_is_not_followed(pin_client: TestClient) -> None:
    response = login(pin_client, next_url="//evil.example/phish")
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_secret_file_created_once_with_mode_600(pin_settings: Settings, tmp_path: Path) -> None:
    first = auth.load_secret(pin_settings.data_dir)
    assert len(first) == 32
    secret_path = pin_settings.data_dir / "secret"
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert auth.load_secret(pin_settings.data_dir) == first
