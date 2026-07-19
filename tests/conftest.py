import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wingman import db
from wingman.app import create_app
from wingman.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


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
