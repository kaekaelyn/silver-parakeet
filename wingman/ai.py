"""AI providers: subscription CLIs, never API keys.

Each provider shells out to an installed CLI (`claude -p`, `codex exec`)
authenticated through the user's own subscription login. Every consumer
must treat a None result as "no AI right now" and fall back gracefully —
degraded operation is tested behavior, not an aspiration.
"""

import json
import logging
import re
import shutil
import sqlite3
import subprocess
from abc import ABC, abstractmethod
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

PROVIDER_KEY = "ai.provider"
CALL_TIMEOUT_SECONDS = 120

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first JSON object out of CLI output (fences and chatter ignored)."""
    match = _JSON_BLOCK.search(text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class AIProvider(ABC):
    name: ClassVar[str]
    label: ClassVar[str]
    binary: ClassVar[str | None] = None

    def available(self) -> tuple[bool, str]:
        """Cheap local check: is the CLI installed? (No network, no auth check.)"""
        if self.binary is None:
            return True, "always available (heuristics and templates)"
        path = shutil.which(self.binary)
        if path is None:
            return False, f"`{self.binary}` CLI not found on PATH"
        return True, f"CLI found at {path}"

    @abstractmethod
    def complete(
        self, system: str, prompt: str, json_schema: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Run one completion; None on any failure (missing, error, garbage)."""

    def _run(self, argv: list[str]) -> str | None:
        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=CALL_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            logger.warning("%s: binary not found", self.name)
            return None
        except subprocess.TimeoutExpired:
            logger.warning("%s: call timed out after %ss", self.name, CALL_TIMEOUT_SECONDS)
            return None
        except OSError as exc:
            logger.warning("%s: could not run CLI: %s", self.name, exc)
            return None
        if result.returncode != 0:
            logger.warning(
                "%s: CLI exited %d: %s", self.name, result.returncode, result.stderr[:300]
            )
            return None
        return result.stdout

    @staticmethod
    def _schema_instruction(json_schema: dict[str, Any] | None) -> str:
        if not json_schema:
            return "Respond with a single JSON object."
        return (
            "Respond with ONLY a single JSON object (no prose, no code fences) "
            f"matching this schema: {json.dumps(json_schema)}"
        )


class ClaudeCLIProvider(AIProvider):
    name = "claude"
    label = "Claude (Claude Code CLI)"
    binary = "claude"

    def complete(
        self, system: str, prompt: str, json_schema: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        full_prompt = f"{system}\n\n{prompt}\n\n{self._schema_instruction(json_schema)}"
        stdout = self._run([self.binary, "-p", full_prompt, "--output-format", "json"])
        if stdout is None:
            return None
        # `claude -p --output-format json` wraps the answer in an envelope
        # whose `result` field holds the model's text.
        envelope = extract_json(stdout)
        if envelope is None:
            logger.warning("%s: output was not JSON", self.name)
            return None
        result_text = envelope.get("result")
        if not isinstance(result_text, str):
            logger.warning("%s: envelope had no result text", self.name)
            return None
        answer = extract_json(result_text)
        if answer is None:
            logger.warning("%s: result text contained no JSON object", self.name)
        return answer


class CodexCLIProvider(AIProvider):
    name = "codex"
    label = "ChatGPT (Codex CLI)"
    binary = "codex"

    def complete(
        self, system: str, prompt: str, json_schema: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        full_prompt = f"{system}\n\n{prompt}\n\n{self._schema_instruction(json_schema)}"
        stdout = self._run([self.binary, "exec", full_prompt])
        if stdout is None:
            return None
        answer = extract_json(stdout)
        if answer is None:
            logger.warning("%s: output contained no JSON object", self.name)
        return answer


class NullProvider(AIProvider):
    name = "none"
    label = "No AI (heuristics and templates)"
    binary = None

    def complete(
        self, system: str, prompt: str, json_schema: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        return None


PROVIDERS: dict[str, AIProvider] = {
    provider.name: provider
    for provider in (ClaudeCLIProvider(), CodexCLIProvider(), NullProvider())
}


def get_provider_name(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value FROM profile WHERE key = ?", (PROVIDER_KEY,)).fetchone()
    name = row["value"] if row else "none"
    return name if name in PROVIDERS else "none"


def get_provider(conn: sqlite3.Connection) -> AIProvider:
    return PROVIDERS[get_provider_name(conn)]


def set_provider_name(conn: sqlite3.Connection, name: str) -> None:
    if name not in PROVIDERS:
        raise ValueError(f"unknown AI provider {name!r}")
    conn.execute(
        """INSERT INTO profile (key, value) VALUES (?, ?)
           ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
        (PROVIDER_KEY, name),
    )
    conn.commit()


def last_call_status(conn: sqlite3.Connection) -> sqlite3.Row | None:
    """Most recent ai.* event, for the health page."""
    return conn.execute(
        """SELECT kind, ts, payload_json FROM events
           WHERE kind IN ('ai.ok', 'ai.error') ORDER BY id DESC LIMIT 1"""
    ).fetchone()
