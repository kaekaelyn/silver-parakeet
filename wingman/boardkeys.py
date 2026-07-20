"""API keys for keyed job boards (Adzuna, USAJOBS).

Keys are entered on the Sources page and stored in the profile table —
every Andy-specific parameter is enterable in the app UI. The config env
file / process environment is a fallback for people who prefer files
(PLAN §10). These are ordinary job-board API keys; the no-API-keys rule
is about AI providers and does not apply here (PLAN §3 Tier A).
"""

import os
import sqlite3

from wingman.config import DEFAULT_ENV_FILE, parse_env_file

KEYED_KINDS = ("adzuna", "usajobs")

# kind -> ((config field, profile key, env var, UI label), ...)
KEY_FIELDS: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "adzuna": (
        ("app_id", "keys.adzuna_app_id", "WINGMAN_ADZUNA_APP_ID", "Application ID"),
        ("app_key", "keys.adzuna_app_key", "WINGMAN_ADZUNA_APP_KEY", "Application key"),
    ),
    "usajobs": (
        ("api_key", "keys.usajobs_api_key", "WINGMAN_USAJOBS_API_KEY", "API key"),
        ("email", "keys.usajobs_email", "WINGMAN_USAJOBS_EMAIL", "Account email"),
    ),
}

SIGNUP_URLS = {
    "adzuna": "https://developer.adzuna.com",
    "usajobs": "https://developer.usajobs.gov",
}


def board_keys(conn: sqlite3.Connection, kind: str) -> dict[str, str]:
    """Resolved key values for one board: profile table first, then env."""
    profile_keys = [profile_key for _f, profile_key, _e, _l in KEY_FIELDS[kind]]
    placeholders = ", ".join("?" for _ in profile_keys)
    stored = dict(
        conn.execute(
            f"SELECT key, value FROM profile WHERE key IN ({placeholders})", profile_keys
        ).fetchall()
    )
    env = parse_env_file(DEFAULT_ENV_FILE)
    env.update({k: v for k, v in os.environ.items() if k.startswith("WINGMAN_")})
    return {
        field: ((stored.get(profile_key) or "").strip() or (env.get(env_var) or "").strip())
        for field, profile_key, env_var, _label in KEY_FIELDS[kind]
    }


def keys_present(conn: sqlite3.Connection, kind: str) -> bool:
    return all(board_keys(conn, kind).values())
