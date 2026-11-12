from __future__ import annotations

from sidecar.audit import AuditLog, redact_command, render_text, summarize


def test_append_and_read_round_trip(tmp_path):
    log = AuditLog(tmp_path)
    log.append({"id": "a", "command": "pwd", "decision": "allow", "returncode": 0})
    log.append({"id": "b", "command": "ls", "decision": "ask", "approval": "approved", "returncode": 0})
    entries = log.read()
    assert [entry["id"] for entry in entries] == ["a", "b"]
    assert entries[1]["approval"] == "approved"


def test_disabled_log_writes_nothing(tmp_path):
    log = AuditLog(tmp_path, enabled=False)
    log.append({"command": "pwd", "decision": "allow"})
    assert not log.path.exists()
    assert log.read() == []


def test_log_rotates_when_it_grows(tmp_path):
    log = AuditLog(tmp_path, max_bytes=64 * 1024)
    for i in range(200):
        log.append({"command": f"echo {i} " + "x" * 400, "decision": "allow"})
    assert log.rotated.exists()
    assert log.path.exists()


def test_summary_counts_decisions_and_errors():
    entries = [
        {"decision": "allow", "returncode": 0},
        {"decision": "ask", "approval": "approved", "returncode": 1},
        {"decision": "deny", "returncode": None},
    ]
    counts = summarize(entries)
    assert counts["total"] == 3
    assert counts["allowed"] == 1
    assert counts["approved"] == 1
    assert counts["denied"] == 1
    assert counts["errors"] == 1


def test_render_text_is_readable(tmp_path):
    log = AuditLog(tmp_path)
    log.append({"command": "pwd", "decision": "allow", "returncode": 0})
    text = render_text(log.read())
    assert "Sidecar audit" in text
    assert "pwd" in text
    assert "1 commands" in text


def test_redact_command_hides_common_secrets():
    command = (
        "curl -H 'Authorization: Bearer abcdefghijklmnop' "
        "--token=supersecret API_KEY=another-secret "
        "https://user:password@example.com/x"
    )
    redacted = redact_command(command)
    assert "abcdefghijklmnop" not in redacted
    assert "supersecret" not in redacted
    assert "another-secret" not in redacted
    assert "password@example.com" not in redacted
    assert "[redacted]" in redacted


def test_audit_store_redacts_secrets(tmp_path):
    log = AuditLog(tmp_path)
    log.append({"command": "TOKEN=abc123secret do-thing", "decision": "ask"})
    stored = log.read()[0]["command"]
    assert "abc123secret" not in stored
    assert "[redacted]" in stored


def test_corrupt_lines_are_ignored(tmp_path):
    log = AuditLog(tmp_path)
    log.path.parent.mkdir(parents=True, exist_ok=True)
    log.path.write_text('{"command": "pwd", "decision": "allow"}\nnot json\n', encoding="utf-8")
    assert len(log.read()) == 1
