"""PIN-gate primitives: per-install secret and the auth cookie value.

The gate itself (middleware) lives in create_app; the login form lives in
routes/auth.py. The cookie carries hmac-sha256("ok") keyed with a random
per-install secret, so a stolen or guessed PIN string never appears in the
cookie and cookies can't be forged without the secret file.
"""

import hashlib
import hmac
import secrets
from pathlib import Path

COOKIE_NAME = "wingman_auth"
COOKIE_MAX_AGE = 365 * 24 * 3600

_LOOPBACK_HOSTS = ("127.0.0.1", "::1")


def load_secret(data_dir: Path) -> bytes:
    """Return the per-install secret, creating it (32 bytes, mode 600) at first use."""
    path = data_dir / "secret"
    if path.is_file():
        return path.read_bytes()
    data_dir.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600)
    path.chmod(0o600)  # touch mode is masked by umask; force it
    path.write_bytes(secrets.token_bytes(32))
    return path.read_bytes()


def cookie_value(secret: bytes) -> str:
    return hmac.new(secret, b"ok", hashlib.sha256).hexdigest()


def cookie_is_valid(presented: str, secret: bytes) -> bool:
    return hmac.compare_digest(presented, cookie_value(secret))


def is_loopback(host: str | None) -> bool:
    return host in _LOOPBACK_HOSTS
