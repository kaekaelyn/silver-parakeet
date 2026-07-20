import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wingman import db
from wingman.app import create_app
from wingman.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def browser_executable() -> Path | None:
    """Chromium override for environments where playwright's own is absent."""
    for candidate in (os.environ.get("WINGMAN_BROWSER"), "/opt/pw-browsers/chromium"):
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", browser_path=browser_executable())


@pytest.fixture(scope="session")
def browser():
    """Session-scoped headless chromium for filler tests."""
    from playwright.sync_api import Error, sync_playwright

    kwargs = {}
    executable = browser_executable()
    if executable:
        kwargs["executable_path"] = str(executable)
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(headless=True, **kwargs)
        except Error as exc:
            pytest.skip(f"chromium unavailable: {str(exc).splitlines()[0]}")
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    new_page = browser.new_page()
    yield new_page
    new_page.close()


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated throwaway database connection."""
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, with_scheduler=False)) as test_client:
        yield test_client
