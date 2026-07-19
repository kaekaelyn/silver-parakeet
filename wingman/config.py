"""Settings loaded from defaults, ~/.config/wingman/env, and process env.

Precedence (lowest to highest): built-in defaults, the env file, process
environment variables. Only WINGMAN_* keys are recognized.
"""

import os
from pathlib import Path

from pydantic import BaseModel

DEFAULT_ENV_FILE = Path.home() / ".config" / "wingman" / "env"
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "wingman"


class Settings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8484
    data_dir: Path = DEFAULT_DATA_DIR

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wingman.db"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a KEY=VALUE file; blank lines and #-comments are ignored."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def load_settings(env_file: Path | None = None) -> Settings:
    merged = parse_env_file(env_file or DEFAULT_ENV_FILE)
    merged.update({k: v for k, v in os.environ.items() if k.startswith("WINGMAN_")})

    kwargs: dict[str, object] = {}
    if "WINGMAN_HOST" in merged:
        kwargs["host"] = merged["WINGMAN_HOST"]
    if "WINGMAN_PORT" in merged:
        kwargs["port"] = int(merged["WINGMAN_PORT"])
    if "WINGMAN_DATA_DIR" in merged:
        kwargs["data_dir"] = Path(merged["WINGMAN_DATA_DIR"]).expanduser()
    return Settings(**kwargs)
