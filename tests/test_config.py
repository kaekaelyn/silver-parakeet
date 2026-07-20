from pathlib import Path

import pytest

from wingman.config import ConfigError, Settings, load_settings, parse_env_file


def test_defaults(tmp_path: Path) -> None:
    settings = load_settings(env_file=tmp_path / "missing")
    assert settings.host == "127.0.0.1"
    assert settings.port == 8484
    assert settings.db_path.name == "wingman.db"


def test_parse_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text(
        "# comment\n"
        "\n"
        "WINGMAN_PORT=9000\n"
        'WINGMAN_HOST="0.0.0.0"\n'
        "not a kv line\n"
        "OTHER_KEY=ignored\n"
        "WINGMAN_DATA_DIR = /tmp/wm \n"
    )
    values = parse_env_file(env_file)
    assert values == {
        "WINGMAN_PORT": "9000",
        "WINGMAN_HOST": "0.0.0.0",
        "WINGMAN_DATA_DIR": "/tmp/wm",
    }


def test_inline_comments_stripped(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text(
        'WINGMAN_PORT=9000  # custom port for laptop\nWINGMAN_HOST="10.0.0.1 # not a comment"\n'
    )
    values = parse_env_file(env_file)
    assert values["WINGMAN_PORT"] == "9000"
    assert values["WINGMAN_HOST"] == "10.0.0.1 # not a comment"


def test_invalid_port_raises_config_error(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text("WINGMAN_PORT=84s4\n")
    with pytest.raises(ConfigError, match="WINGMAN_PORT"):
        load_settings(env_file=env_file)


def test_env_file_applied(tmp_path: Path) -> None:
    env_file = tmp_path / "env"
    env_file.write_text(f"WINGMAN_PORT=9000\nWINGMAN_DATA_DIR={tmp_path}/data\n")
    settings = load_settings(env_file=env_file)
    assert settings.port == 9000
    assert settings.data_dir == tmp_path / "data"


def test_process_env_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / "env"
    env_file.write_text("WINGMAN_PORT=9000\n")
    monkeypatch.setenv("WINGMAN_PORT", "9001")
    settings = load_settings(env_file=env_file)
    assert settings.port == 9001


def test_derived_paths() -> None:
    settings = Settings(data_dir=Path("/x"))
    assert settings.db_path == Path("/x/wingman.db")
    assert settings.documents_dir == Path("/x/documents")
