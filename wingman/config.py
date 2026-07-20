"""Settings loaded from defaults, ~/.config/wingman/env, and process env.

Precedence (lowest to highest): built-in defaults, the env file, process
environment variables. Only WINGMAN_* keys are recognized. Invalid values
raise ConfigError with a message naming the offending key.
"""

import os
import re
from pathlib import Path

from pydantic import BaseModel

DEFAULT_ENV_FILE = Path.home() / ".config" / "wingman" / "env"
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / "wingman"

_INLINE_COMMENT = re.compile(r"\s+#")


class ConfigError(ValueError):
    """A configuration value is invalid; the message names the key."""


class Settings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8484
    data_dir: Path = DEFAULT_DATA_DIR
    # Optional chromium executable override (WINGMAN_BROWSER). Default:
    # the browser `playwright install chromium` puts in its own cache.
    browser_path: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wingman.db"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse WINGMAN_* keys from a KEY=VALUE file.

    Blank lines and #-comments (whole-line, or trailing an unquoted value)
    are ignored; quoted values keep their content verbatim.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.startswith("WINGMAN_"):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = _INLINE_COMMENT.split(value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def load_settings(env_file: Path | None = None) -> Settings:
    merged = parse_env_file(env_file or DEFAULT_ENV_FILE)
    merged.update({k: v for k, v in os.environ.items() if k.startswith("WINGMAN_")})

    kwargs: dict[str, object] = {}
    if "WINGMAN_HOST" in merged:
        kwargs["host"] = merged["WINGMAN_HOST"]
    if "WINGMAN_PORT" in merged:
        raw_port = merged["WINGMAN_PORT"]
        try:
            kwargs["port"] = int(raw_port)
        except ValueError as exc:
            raise ConfigError(f"WINGMAN_PORT must be an integer, got {raw_port!r}") from exc
    if "WINGMAN_DATA_DIR" in merged:
        kwargs["data_dir"] = Path(merged["WINGMAN_DATA_DIR"]).expanduser()
    if merged.get("WINGMAN_BROWSER"):
        kwargs["browser_path"] = Path(merged["WINGMAN_BROWSER"]).expanduser()
    return Settings(**kwargs)
