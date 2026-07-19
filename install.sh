#!/usr/bin/env bash
# Wingman installer: uv sync, config + db init, playwright browser (when the
# dependency exists), systemd user unit. Safe to re-run.
set -euo pipefail

cd "$(dirname "$0")"
REPO_DIR="$(pwd)"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: uv is required. Install it first:" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi
UV_BIN="$(command -v uv)"

echo "==> Installing dependencies (uv sync)"
uv sync

echo "==> Preparing config and data directories"
CONFIG_DIR="${HOME}/.config/wingman"
mkdir -p "${CONFIG_DIR}"
if [ ! -f "${CONFIG_DIR}/env" ]; then
    (umask 177 && cat > "${CONFIG_DIR}/env" <<'EOF'
# Wingman configuration (KEY=VALUE). Loaded at startup; process env overrides.
# WINGMAN_HOST=127.0.0.1
# WINGMAN_PORT=8484
# WINGMAN_DATA_DIR=~/.local/share/wingman
EOF
    )
    echo "    created ${CONFIG_DIR}/env (mode 600)"
fi

echo "==> Initializing database"
uv run wingman init-db

# Playwright ships with the apply engine (M5). Install its browser only once
# the dependency is present so early installs stay small.
if uv run python -c "import playwright" >/dev/null 2>&1; then
    echo "==> Installing Playwright Chromium"
    uv run playwright install chromium
else
    echo "==> Skipping Playwright browser (not yet a dependency; arrives with the apply engine)"
fi

echo "==> Installing systemd user service"
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    UNIT_DIR="${HOME}/.config/systemd/user"
    mkdir -p "${UNIT_DIR}"
    sed -e "s|@WORKDIR@|${REPO_DIR}|g" -e "s|@UV@|${UV_BIN}|g" \
        systemd/wingman.service.in > "${UNIT_DIR}/wingman.service"
    systemctl --user daemon-reload
    systemctl --user enable --now wingman.service
    echo "    service enabled and started (systemctl --user status wingman)"
else
    echo "    systemd user session not available; run manually with: make dev"
fi

echo
echo "Wingman installed. Open http://127.0.0.1:8484"
