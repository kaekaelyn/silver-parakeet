from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8484
    data_dir: Path = Path.home() / ".local" / "share" / "wingman"
    config_file: Path = Path.home() / ".config" / "wingman" / "env"

    @property
    def database_path(self) -> Path:
        return self.data_dir / "wingman.sqlite3"


def load_settings() -> Settings:
    defaults = Settings()
    values: dict[str, str] = {}
    if defaults.config_file.exists():
        for line in defaults.config_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return Settings(
        host=values.get("WINGMAN_HOST", defaults.host),
        port=int(values.get("WINGMAN_PORT", defaults.port)),
        data_dir=Path(values.get("WINGMAN_DATA_DIR", str(defaults.data_dir))).expanduser(),
        config_file=defaults.config_file,
    )
