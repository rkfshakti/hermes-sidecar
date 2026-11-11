"""Append-only local audit log for Sidecar.

Only metadata is stored: timestamp, command text (bounded), cwd, decision,
approval, exit code, duration, output size and a short error label. Command
output is never stored. The log is local to the machine running the daemon and
is never uploaded.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Iterable

MAX_ENTRY_COMMAND = 4000
DEFAULT_MAX_BYTES = 5 * 1024 * 1024

_REDACTIONS = (
    (re.compile(r"(?i)(--?(?:token|password|passwd|secret|api[-_]?key)\s*[= ]\s*)(\S+)"), r"\1[redacted]"),
    (re.compile(r"(?i)(authorization:\s*(?:bearer|basic)\s+)(\S+)"), r"\1[redacted]"),
    (re.compile(r"(?i)((?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|ACCESS_KEY|PRIVATE_KEY)\s*=\s*)(\S+)"), r"\1[redacted]"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1[redacted]"),
    (re.compile(r"(?i)(https?://[^/\s:@]+:)([^/\s@]+)(@)"), r"\1[redacted]\3"),
)


def redact_command(command: str) -> str:
    """Best-effort secret redaction for the audit copy of a command."""
    text = str(command or "")
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class AuditLog:
    """A bounded JSONL log with one rotated file."""

    def __init__(self, data_dir: str | os.PathLike[str], *, enabled: bool = True, max_bytes: int = DEFAULT_MAX_BYTES):
        self.dir = Path(data_dir)
        self.path = self.dir / "audit.jsonl"
        self.rotated = self.dir / "audit.jsonl.1"
        self.enabled = bool(enabled)
        self.max_bytes = max(64 * 1024, int(max_bytes))
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.dir, 0o700)
        except OSError:
            pass

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size >= self.max_bytes:
                if self.rotated.exists():
                    self.rotated.unlink()
                self.path.replace(self.rotated)
        except OSError:
            # A read-only or full disk must not take the daemon down.
            pass

    def append(self, entry: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return entry
        record = {
            "ts": _now(),
            "id": str(entry.get("id") or ""),
            "command": redact_command(str(entry.get("command") or ""))[:MAX_ENTRY_COMMAND],
            "cwd": str(entry.get("cwd") or ""),
            "decision": str(entry.get("decision") or ""),
            "reason": str(entry.get("reason") or "")[:500],
            "approval": str(entry.get("approval") or ""),
            "returncode": entry.get("returncode"),
            "duration_ms": entry.get("duration_ms"),
            "output_bytes": entry.get("output_bytes"),
            "truncated": bool(entry.get("truncated", False)),
            "client": str(entry.get("client") or "")[:200],
        }
        with self._lock:
            self._ensure()
            self._rotate_if_needed()
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
            except OSError:
                pass
        return record

    def read(self, limit: int = 20) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for path in (self.rotated, self.path):
            try:
                if not path.exists():
                    continue
                with path.open("r", encoding="utf-8", errors="replace") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            value = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(value, dict):
                            records.append(value)
            except OSError:
                continue
        records.sort(key=lambda item: str(item.get("ts") or ""))
        if limit and limit > 0:
            return records[-limit:]
        return records

    def clear(self) -> None:
        with self._lock:
            for path in (self.path, self.rotated):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    def count(self) -> int:
        return len(self.read(limit=0))


def summarize(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    items = list(entries)
    counts = {"total": len(items), "allowed": 0, "denied": 0, "asked": 0, "approved": 0, "errors": 0}
    for entry in items:
        decision = str(entry.get("decision") or "")
        if decision == "allow":
            counts["allowed"] += 1
        elif decision == "deny":
            counts["denied"] += 1
        elif decision == "ask":
            counts["asked"] += 1
        approval = str(entry.get("approval") or "")
        if approval == "approved":
            counts["approved"] += 1
        code = entry.get("returncode")
        if isinstance(code, int) and code != 0:
            counts["errors"] += 1
    return counts


def render_text(entries: Iterable[dict[str, Any]], *, limit: int = 20) -> str:
    items = list(entries)
    if limit and limit > 0:
        items = items[-limit:]
    if not items:
        return "Sidecar audit: no commands recorded yet."
    lines = [
        "Sidecar audit (newest last)",
        "────────────────────────────────────────────────────────────────────────",
    ]
    for entry in items:
        code = entry.get("returncode")
        code_text = "" if code is None else f" exit={code}"
        decision = str(entry.get("decision") or "?")
        approval = str(entry.get("approval") or "")
        marker = {"allow": "✓", "deny": "⛔", "ask": "?"}.get(decision, "·")
        suffix = f" [{approval}]" if approval else ""
        command = str(entry.get("command") or "").replace("\n", " ")
        if len(command) > 110:
            command = command[:107] + "..."
        lines.append(
            f"{marker} {str(entry.get('ts') or '')[:19]}  {decision:<5}{suffix:<11}{code_text:<8} {command}"
        )
        cwd = entry.get("cwd")
        if cwd:
            lines.append(f"    cwd: {cwd}")
        reason = entry.get("reason")
        if reason and decision != "allow":
            lines.append(f"    {reason}")
    counts = summarize(items)
    lines.append("────────────────────────────────────────────────────────────────────────")
    lines.append(
        f"{counts['total']} commands · {counts['allowed']} auto-allowed · "
        f"{counts['approved']} approved · {counts['denied']} denied · {counts['errors']} non-zero"
    )
    return "\n".join(lines)
