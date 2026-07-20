import json
import sqlite3
import stat
from pathlib import Path

import pytest

from wingman import ai


def _fake_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, script: str) -> None:
    """Put an executable fake CLI named `name` on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{script}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", str(bin_dir))


def test_extract_json_variants() -> None:
    assert ai.extract_json('{"a": 1}') == {"a": 1}
    assert ai.extract_json('chatter\n```json\n{"a": 1}\n```\nmore') == {"a": 1}
    assert ai.extract_json("no json here") is None
    assert ai.extract_json("[1, 2, 3]") is None  # object required
    assert ai.extract_json("{broken") is None


def test_claude_missing_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))  # empty dir: no claude anywhere
    provider = ai.ClaudeCLIProvider()
    ok, detail = provider.available()
    assert not ok and "not found" in detail
    assert provider.complete("s", "p") is None


def test_claude_nonzero_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_cli(tmp_path, monkeypatch, "claude", 'echo "auth expired" >&2; exit 1')
    assert ai.ClaudeCLIProvider().complete("s", "p") is None


def test_claude_garbage_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_cli(tmp_path, monkeypatch, "claude", "echo 'not json at all'")
    assert ai.ClaudeCLIProvider().complete("s", "p") is None


def test_claude_valid_envelope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    envelope = json.dumps({"type": "result", "result": 'Here you go: {"score": 88}'})
    _fake_cli(tmp_path, monkeypatch, "claude", f"echo '{envelope}'")
    provider = ai.ClaudeCLIProvider()
    assert provider.available()[0]
    assert provider.complete("s", "p") == {"score": 88}


def test_claude_called_with_tools_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Prompts carry untrusted job-board text: every call must disable CLI tools.
    argv_log = tmp_path / "argv"
    envelope = json.dumps({"result": "{}"})
    _fake_cli(tmp_path, monkeypatch, "claude", f"echo \"$@\" > {argv_log}; echo '{envelope}'")
    ai.ClaudeCLIProvider().complete("s", "p")
    assert "--tools" in argv_log.read_text().split()


def test_codex_plain_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_cli(tmp_path, monkeypatch, "codex", "echo 'thinking...'; echo '{\"ok\": true}'")
    assert ai.CodexCLIProvider().complete("s", "p") == {"ok": True}


def test_null_provider() -> None:
    provider = ai.NullProvider()
    assert provider.available()[0]
    assert provider.complete("s", "p") is None


def test_feature_toggles_default_on_and_roundtrip(conn: sqlite3.Connection) -> None:
    assert ai.feature_states(conn) == {feature: True for feature in ai.FEATURES}
    ai.set_feature_enabled(conn, "scoring", False)
    assert not ai.feature_enabled(conn, "scoring")
    assert ai.feature_enabled(conn, "letters")  # switches are independent
    assert ai.feature_enabled(conn, "tailoring")
    ai.set_feature_enabled(conn, "scoring", True)
    assert ai.feature_enabled(conn, "scoring")
    with pytest.raises(ValueError):
        ai.feature_enabled(conn, "skynet")
    with pytest.raises(ValueError):
        ai.set_feature_enabled(conn, "skynet", True)


def test_provider_for_feature_respects_toggle(conn: sqlite3.Connection) -> None:
    ai.set_provider_name(conn, "claude")
    assert ai.provider_for_feature(conn, "scoring").name == "claude"
    ai.set_feature_enabled(conn, "scoring", False)
    assert ai.provider_for_feature(conn, "scoring").name == "none"
    # Other features keep the real provider.
    assert ai.provider_for_feature(conn, "letters").name == "claude"


def test_provider_selection_roundtrip(conn: sqlite3.Connection) -> None:
    assert ai.get_provider_name(conn) == "none"
    ai.set_provider_name(conn, "claude")
    assert ai.get_provider_name(conn) == "claude"
    with pytest.raises(ValueError):
        ai.set_provider_name(conn, "skynet")
    # A stale/unknown stored value degrades to none instead of crashing.
    conn.execute("UPDATE profile SET value = 'gone' WHERE key = ?", (ai.PROVIDER_KEY,))
    conn.commit()
    assert ai.get_provider_name(conn) == "none"
