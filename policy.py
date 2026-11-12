"""Command policy for the Sidecar daemon.

Sidecar is a consent gate, not a kernel sandbox. Every command is either:

* ``allow`` — a small set of side-effect-free, argument-free read-only commands
  that run without a prompt (``pwd``, ``echo``, ``date``, ...);
* ``ask``   — the local user sees the command and approves or denies it;
* ``deny``  — a catastrophic pattern that is refused outright (``sudo``,
  ``rm -rf /``, ``curl | sh``, ``osascript``, ...).

The deny list is deliberately narrow and explainable. It is a last line of
defence for obvious mistakes, not a replacement for the approval prompt or for
an OS sandbox such as Glassbox.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

APPROVAL_MODES = ("ask", "allow", "read-only", "deny")
DEFAULT_APPROVAL = "ask"
DEFAULT_MAX_TIMEOUT = 600
DEFAULT_TIMEOUT = 300
DEFAULT_MAX_COMMAND_BYTES = 64 * 1024
DEFAULT_MAX_OUTPUT_BYTES = 2 * 1024 * 1024

# Shell syntax that turns a simple command into a pipeline, redirect, subshell
# or command substitution. A "simple" command has none of these, so the allow
# list cannot be used to smuggle a read or a write past the approval prompt.
_SHELL_META = re.compile(r"[;&|<>`$(){}\[\]*?!\n\r]")

# Commands whose arguments are harmless and whose whole job is to print a fact
# about the current process or machine. They are allowed without a prompt only
# when the command contains no shell metacharacters.
_SAFE_SIMPLE = frozenset({
    "pwd", "echo", "printf", "true", "false", "date", "whoami", "id",
    "uname", "hostname", "sw_vers", "arch", "tty",
})

# (pattern, reason) — case-insensitive, searched anywhere in the command.
_DENY_RULES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), reason)
    for pattern, reason in (
        (r"(^|[\s;|&])sudo(\s|$)", "privilege escalation (sudo)"),
        (r"(^|[\s;|&])doas(\s|$)", "privilege escalation (doas)"),
        (r"\bmkfs(\.|\s|$)", "filesystem format"),
        (r"\bdd\s+if=", "raw disk copy"),
        (r"\bdiskutil\s+(erase|partition|secureErase|zeroDisk|randomDisk)\b", "disk erase"),
        (r"\bcsrutil\s+disable\b", "disabling System Integrity Protection"),
        (r"\b(shutdown|reboot|halt|poweroff)\b", "machine power control"),
        (r"\bkill(all)?\s+-9\s+1(?:\s|$)", "killing PID 1"),
        (r"\blaunchctl\s+(unload|load|bootstrap|bootout|disable|enable|submit)\b", "launchd job control"),
        (r"\bdefaults\s+write\b", "writing macOS preferences"),
        (r"\bsecurity\s+(find|delete|dump|import|export|add|set|unlock|lock)-", "keychain access"),
        (r"\bosascript\b", "Apple Events automation"),
        (r"\bopen\s+-a\b", "launching a GUI application"),
        (r"\b(curl|wget)\b[^\n|]*\|\s*(bash|sh|zsh|fish|python[0-9.]*)\b", "piping a download into an interpreter"),
        (r"(^|[\s;|&])(ssh|scp|sftp|nc|ncat|socat|telnet)(\s|$)", "outbound network shell"),
        (r"\bchmod\s+(-R\s+)?777\s+/(?:\s|$)", "world-writable root"),
        (r"\bchown\s+(-R\s+)?[^\s]+\s+/(?:\s|$)", "changing ownership of root"),
        (r"\b(history\s+-c|unset\s+HISTFILE)\b", "clearing shell history"),
        (r"\b(base64|xxd)\b[^\n|]*\|\s*(base64|xxd)\s+-d[^\n|]*\|\s*(bash|sh|zsh)\b", "encoded payload execution"),
    )
)


@dataclass(frozen=True)
class Decision:
    """The policy verdict for one command."""

    action: str            # "allow" | "ask" | "deny"
    reason: str
    matched: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    @property
    def needs_approval(self) -> bool:
        return self.action == "ask"

    def as_dict(self) -> dict[str, str]:
        return {"action": self.action, "reason": self.reason, "matched": self.matched}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def normalize_settings(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a validated settings dict with safe defaults.

    Unknown keys are ignored. Invalid values fall back to the default rather than
    making the daemon fail to start; the status output shows the effective policy.
    """
    data = dict(raw or {})
    approval = str(data.get("approval") or DEFAULT_APPROVAL).strip().lower()
    if approval not in APPROVAL_MODES:
        approval = DEFAULT_APPROVAL
    try:
        timeout = int(data.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    timeout = max(1, min(timeout, DEFAULT_MAX_TIMEOUT))
    try:
        max_timeout = int(data.get("max_timeout") or DEFAULT_MAX_TIMEOUT)
    except (TypeError, ValueError):
        max_timeout = DEFAULT_MAX_TIMEOUT
    max_timeout = max(1, min(max_timeout, 24 * 3600))
    workspace = str(data.get("workspace") or "~").strip() or "~"
    return {
        "approval": approval,
        "timeout": timeout,
        "max_timeout": max_timeout,
        "workspace": workspace,
        "allow": _as_list(data.get("allow")),
        "deny": _as_list(data.get("deny")),
        "allow_outside_workspace": bool(data.get("allow_outside_workspace", False)),
        "audit": bool(data.get("audit", True)),
        "max_output_bytes": int(data.get("max_output_bytes") or DEFAULT_MAX_OUTPUT_BYTES),
        "max_command_bytes": int(data.get("max_command_bytes") or DEFAULT_MAX_COMMAND_BYTES),
        "max_concurrent": max(1, min(int(data.get("max_concurrent") or 4), 32)),
    }


def resolve_workspace(value: str | os.PathLike[str] | None, *, fallback: Path | None = None) -> Path:
    text = str(value or "~")
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    try:
        path = path.resolve()
    except OSError:
        path = path.absolute()
    if path.is_dir():
        return path
    return (fallback or Path.home()).resolve()


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _custom_rule(command: str, patterns: Iterable[str]) -> str:
    for pattern in patterns:
        try:
            if re.search(pattern, command, re.IGNORECASE):
                return pattern
        except re.error:
            # A bad user regex must not crash the daemon; ignore it.
            continue
    return ""


_SHELL_OPERATORS = frozenset({";", ";;", "&", "&&", "|", "||", "(", ")"})
_ROOT_DELETE_TARGETS = frozenset({"/", "/*", "~", "~/", "$HOME", "${HOME}", "/root"})


def _shell_tokens(command: str) -> list[str]:
    """Tokenize without regex backtracking on attacker-controlled command text."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _rm_flags_recursive(flags: Iterable[str]) -> bool:
    for flag in flags:
        if flag == "--recursive":
            return True
        if flag.startswith("--"):
            continue
        if "r" in flag[1:] or "R" in flag[1:]:
            return True
    return False


def _recursive_delete_reason(command: str, *, depth: int = 0) -> str:
    """Linear check for ``rm -r`` against ``/`` or a home directory.

    A token pass avoids the nested-quantifier regex that backtracks quadratically
    on one long ``-rrrr…`` flag. Quoted shell payloads (``sh -c 'rm -rf /'``) are
    tokenized once more, bounded by *depth*.
    """
    try:
        tokens = _shell_tokens(command)
    except ValueError:
        return ""
    for index, token in enumerate(tokens):
        if depth < 2 and "rm" in token and os.path.basename(token) != "rm":
            nested = _recursive_delete_reason(token, depth=depth + 1)
            if nested:
                return nested
        if os.path.basename(token) != "rm":
            continue
        flags: list[str] = []
        cursor = index + 1
        while cursor < len(tokens) and tokens[cursor] not in _SHELL_OPERATORS:
            current = tokens[cursor]
            if current == "--":
                cursor += 1
                break
            if not current.startswith("-") or current == "-":
                break
            flags.append(current)
            cursor += 1
        if not _rm_flags_recursive(flags):
            continue
        while cursor < len(tokens) and tokens[cursor] not in _SHELL_OPERATORS:
            target = tokens[cursor]
            cursor += 1
            normalized = target.rstrip("/")
            if target in _ROOT_DELETE_TARGETS or normalized in {"/", "~", "$HOME", "${HOME}", "/root"}:
                return "recursive delete of /" if target.startswith("/") else "recursive delete of home"
    return ""


def is_safe_simple(command: str) -> bool:
    """True for a side-effect-free command with no shell syntax.

    ``echo hello`` is safe; ``echo hi > file``, ``echo $(cat secret)`` and
    ``ls | sh`` are not. Only the first token is considered, so an allowed
    command cannot be chained to another one.
    """
    text = command.strip()
    if not text or _SHELL_META.search(text):
        return False
    try:
        parts = shlex.split(text)
    except ValueError:
        return False
    if not parts:
        return False
    name = os.path.basename(parts[0]).lower()
    return name in _SAFE_SIMPLE


def classify_command(
    command: str,
    *,
    settings: Mapping[str, Any] | None = None,
    workspace: str | os.PathLike[str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
) -> Decision:
    """Classify one command for the daemon.

    Order: hard denies (including the user's deny list), the safe-simple allow
    list, then the configured approval mode. A command that runs outside the
    configured workspace is never auto-allowed.
    """
    settings = normalize_settings(settings)
    text = (command or "").strip()
    if not text:
        return Decision("deny", "empty command")
    if len(text.encode("utf-8", "replace")) > settings["max_command_bytes"]:
        return Decision("deny", f"command exceeds {settings['max_command_bytes']} bytes")
    if "\x00" in text:
        return Decision("deny", "NUL byte in command")

    for rule, reason in _DENY_RULES:
        if rule.search(text):
            return Decision("deny", reason, rule.pattern)

    rm_reason = _recursive_delete_reason(text)
    if rm_reason:
        return Decision("deny", rm_reason)

    custom_deny = _custom_rule(text, settings["deny"])
    if custom_deny:
        return Decision("deny", "matched the local deny list", custom_deny)

    if settings["approval"] == "deny":
        return Decision("deny", "approval mode is deny")

    workspace_path = resolve_workspace(workspace or settings["workspace"])
    target = resolve_workspace(cwd or workspace_path, fallback=workspace_path)
    inside = is_within(target, workspace_path)

    if not inside and not settings["allow_outside_workspace"]:
        return Decision("deny", f"cwd {target} is outside the configured workspace {workspace_path}")

    custom_allow = _custom_rule(text, settings["allow"])
    if custom_allow:
        return Decision("allow", "matched the local allow list", custom_allow)

    if inside and is_safe_simple(text):
        return Decision("allow", "side-effect-free command")

    mode = settings["approval"]
    if mode == "allow":
        return Decision("allow", "approval mode is allow")
    if mode == "read-only":
        return Decision("deny", "approval mode is read-only and the command is not a safe simple command")
    if mode == "deny":
        return Decision("deny", "approval mode is deny")
    return Decision("ask", "the local user must approve this command")


def policy_summary(settings: Mapping[str, Any] | None = None) -> str:
    settings = normalize_settings(settings)
    workspace = resolve_workspace(settings["workspace"])
    return (
        f"approval={settings['approval']} workspace={workspace} "
        f"timeout={settings['timeout']}s max_timeout={settings['max_timeout']}s "
        f"allow_outside_workspace={settings['allow_outside_workspace']} "
        f"custom_allow={len(settings['allow'])} custom_deny={len(settings['deny'])}"
    )
