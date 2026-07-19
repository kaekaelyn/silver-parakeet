from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wingman.app import create_app
from wingman.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
