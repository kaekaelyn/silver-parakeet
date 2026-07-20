#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/wingman"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$CONFIG_DIR" "$SYSTEMD_DIR"
if [[ ! -f "$CONFIG_DIR/env" ]]; then
  cat > "$CONFIG_DIR/env" <<ENV
WINGMAN_HOST=127.0.0.1
WINGMAN_PORT=8484
WINGMAN_DATA_DIR=$HOME/.local/share/wingman
ENV
  chmod 600 "$CONFIG_DIR/env"
fi
uv sync
uv run wingman init-db
uv run playwright install chromium || true
sed "s|__ROOT__|$ROOT|g" "$ROOT/wingman.service.in" > "$SYSTEMD_DIR/wingman.service"
systemctl --user daemon-reload
systemctl --user enable --now wingman.service || true
printf 'Wingman installed. Open http://127.0.0.1:8484\n'
