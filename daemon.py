"""The local Sidecar daemon.

A small HTTP server bound to loopback by default. The remote Hermes plugin sends
one command per request; the daemon applies the local policy, optionally asks the
person at the machine, runs the command with a sanitized environment, and returns
its output. Every decision is written to a local audit log.

The boundary is the human approval prompt plus the deny list. This is not an OS
sandbox: a command the user approves runs with the user's privileges. Pair it
with Glassbox when you need kernel enforcement.
"""

from __future__ import annotations

import base64
import binascii
import getpass
import json
import logging
import os
import platform
import re
import select
import shlex
import signal
import socket
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Mapping

from . import audit as audit_mod
from . import config as config_mod
from . import policy as policy_mod
from . import pairing as token_mod

logger = logging.getLogger("hermes.sidecar")

VERSION = "1.1.0"
MAX_BODY_BYTES = 2 * 1024 * 1024
APPROVAL_TIMEOUT_S = 120

Approver = Callable[[str, str, int, str], tuple[bool, str]]


def _bash_path() -> str:
    for candidate in ("/bin/bash", "/usr/bin/bash"):
        if Path(candidate).exists():
            return candidate
    return "/bin/sh"


def safe_env(*, cwd: Path) -> dict[str, str]:
    """A deliberately small environment for locally executed commands.

    Provider keys, cloud credentials, SSH agent sockets and every other
    secret-looking variable stay out. A command can still read ``~/.ssh`` if the
    user approves it; the approval prompt is the boundary, not this env.
    """
    keep = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TMPDIR", "TZ")
    env = {name: os.environ[name] for name in keep if os.environ.get(name)}
    env.setdefault("PATH", "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin")
    env.setdefault("AI_AGENT", "hermes-agent")
    env.setdefault("HERMES_AGENT", "true")
    env.setdefault("GIT_PAGER", "cat")
    env.setdefault("PAGER", "cat")
    env["PWD"] = str(cwd)
    env["SIDECAR"] = "1"
    return env


@dataclass
class ServerState:
    token: str
    settings: dict[str, Any]
    workspace: Path
    audit: audit_mod.AuditLog
    approver: Approver
    semaphore: threading.BoundedSemaphore
    hostname: str
    started_at: float
    lock: threading.Lock


def _terminal_approver(command: str, cwd: str, timeout: int, client: str) -> tuple[bool, str]:
    """Ask the person at the machine. Deny when there is no interactive TTY."""
    if not sys.stdin or not sys.stdin.isatty():
        return False, "no interactive terminal on the local machine"
    stamp = time.strftime("%H:%M:%S")
    print("", file=sys.stderr)
    print("┌─ Sidecar approval ─────────────────────────────────────────────", file=sys.stderr)
    print(f"│ {stamp} · {client or 'remote Hermes'} · {timeout}s", file=sys.stderr)
    print(f"│ {cwd}", file=sys.stderr)
    for index, line in enumerate(command.splitlines() or [""]):
        for offset, wrapped in enumerate(textwrap.wrap(line, width=58) or [""]):
            prefix = "│ $ " if index == 0 and offset == 0 else "│   "
            print(prefix + wrapped, file=sys.stderr)
    print("└────────────────────────────────────────────────────────────────", file=sys.stderr)
    print("Approve? [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        ready, _, _ = select.select([sys.stdin], [], [], min(APPROVAL_TIMEOUT_S, max(30, timeout)))
    except (OSError, ValueError):
        return False, "approval prompt failed"
    if not ready:
        print("", file=sys.stderr)
        return False, "approval timed out"
    try:
        answer = sys.stdin.readline().strip().lower()
    except (OSError, KeyboardInterrupt):
        return False, "approval cancelled"
    if answer in ("y", "yes"):
        return True, "approved by the local user"
    return False, "denied by the local user"


def _truncate_output(output: str, limit: int) -> tuple[str, bool]:
    if limit <= 0 or len(output) <= limit:
        return output, False
    head = limit // 2
    tail = limit - head
    marker = f"\n\n... [Sidecar truncated {len(output) - limit} characters] ...\n\n"
    return output[:head] + marker + output[-tail:], True


_EXEC_MARKER = "# sidecar-exec-v2:"
_LEGACY_POLICY_MARKER = "# sidecar-policy-command:"
_CWD_MARKER_RE = re.compile(r"^__HERMES_CWD_[0-9a-f]{12}__$")
_PIPE_MARKER_RE = re.compile(r"^__HERMES_PIPE_[0-9a-f]{12}__$")
_MAX_WRAPPED_COMMAND_BYTES = 256 * 1024


@dataclass(frozen=True)
class ExecRequest:
    """One parsed ``/v1/exec`` request.

    ``policy_command`` is the exact text the daemon classifies, prompts for,
    audits and executes. For protocol-v2 requests the daemon also builds the
    shell wrapper from that text; the client never supplies an executable
    remainder that the policy did not see.
    """

    policy_command: str
    cwd: str | None = None
    cwd_marker: str = ""
    pipe_marker: str = ""
    wrapped: bool = False


def _parse_exec_request(command: str) -> ExecRequest:
    """Parse a v2 envelope, reject the legacy marker, or accept a raw command.

    The old protocol let a client send a benign policy command and a different
    executable script in the same request. That turned the approval prompt into a
    claim about what would run, not the thing that actually ran. The v2 envelope
    carries data only: the daemon builds the wrapper itself.
    """
    first, _, rest = command.partition("\n")
    if first.startswith(_LEGACY_POLICY_MARKER):
        raise ValueError(
            "legacy sidecar-policy-command requests are no longer accepted; "
            "upgrade the remote Sidecar plugin"
        )
    if not first.startswith(_EXEC_MARKER):
        return ExecRequest(policy_command=command)
    if rest.strip():
        raise ValueError("trailing data after the sidecar-exec-v2 header")
    encoded = first[len(_EXEC_MARKER):].strip()
    try:
        decoded = base64.b64decode(encoded.encode("ascii"), validate=True).decode("utf-8")
        payload = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        raise ValueError("invalid sidecar-exec-v2 header") from None
    if not isinstance(payload, dict):
        raise ValueError("sidecar-exec-v2 header must be a JSON object")
    policy_command = payload.get("command")
    cwd = payload.get("cwd")
    marker = payload.get("cwd_marker") or ""
    pipe_marker = payload.get("pipe_marker") or ""
    if not isinstance(policy_command, str) or not policy_command.strip():
        raise ValueError("sidecar-exec-v2 command must be a non-empty string")
    if cwd is not None and not isinstance(cwd, str):
        raise ValueError("sidecar-exec-v2 cwd must be a string")
    if marker and (not isinstance(marker, str) or not _CWD_MARKER_RE.fullmatch(marker)):
        raise ValueError("sidecar-exec-v2 cwd_marker is invalid")
    if pipe_marker and (not isinstance(pipe_marker, str) or not _PIPE_MARKER_RE.fullmatch(pipe_marker)):
        raise ValueError("sidecar-exec-v2 pipe_marker is invalid")
    return ExecRequest(
        policy_command=policy_command,
        cwd=cwd or None,
        cwd_marker=marker,
        pipe_marker=pipe_marker,
        wrapped=True,
    )


def _build_wrapped_command(
    command: str,
    cwd: str,
    cwd_marker: str = "",
    pipe_marker: str = "",
) -> str:
    """Build the shell script the daemon runs, from the command it classified."""
    escaped = command.replace("'", "'\\''")
    capture_pipe = bool(pipe_marker) and "<<" not in command and not command.endswith("\\")
    if capture_pipe:
        eval_line = (
            f"eval '{escaped}\n\n"
            "__hermes_rc=$? __hermes_ps=(\"${PIPESTATUS[@]}\"); "
            "(exit $__hermes_rc) && :'"
        )
    else:
        eval_line = f"eval '{escaped}'"
    lines = [
        f"builtin cd -- {shlex.quote(cwd)} || exit 126",
        eval_line,
        "__hermes_ec=$?",
    ]
    if capture_pipe:
        lines.append(f"printf '\\n{pipe_marker}%s{pipe_marker}\\n' \"${{__hermes_ps[*]-}}\"")
    if cwd_marker:
        lines.append(f"printf '\\n{cwd_marker}%s{cwd_marker}\\n' \"$(pwd -P)\"")
    lines.append("exit $__hermes_ec")
    return "\n".join(lines)


class SidecarHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"Sidecar/{VERSION}"
    sys_version = ""

    @property
    def state(self) -> ServerState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003 - stdlib name
        logger.debug("sidecar http: " + fmt, *args)

    # ---- response helpers ------------------------------------------------

    def _send(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8", "replace")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _error(self, status: int, message: str, *, reason: str = "") -> None:
        self._send(status, {"ok": False, "error": message, "reason": reason})

    def _client_label(self) -> str:
        explicit = self.headers.get("X-Sidecar-Client") or ""
        agent = self.headers.get("User-Agent") or ""
        label = explicit or agent or "remote Hermes"
        return label.strip()[:180]

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization") or ""
        prefix = "Bearer "
        if not header.startswith(prefix):
            self._error(401, "missing bearer token")
            return False
        candidate = header[len(prefix):].strip()
        if not token_mod.tokens_equal(candidate, self.state.token):
            self._error(401, "invalid pairing token")
            return False
        return True

    def _read_json(self, *, max_bytes: int = MAX_BODY_BYTES) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            raise ValueError("empty request body")
        if length > max_bytes:
            raise ValueError(f"request body exceeds {max_bytes} bytes")
        raw = self.rfile.read(length)
        value = json.loads(raw.decode("utf-8", "replace"))
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    # ---- routes ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        if not self._authorized():
            return
        path = self.path.split("?", 1)[0]
        if path == "/v1/health":
            settings = self.state.settings
            self._send(200, {
                "ok": True,
                "version": VERSION,
                "hostname": self.state.hostname,
                "platform": platform.platform(),
                "workspace": str(self.state.workspace),
                "approval": settings["approval"],
                "policy": policy_mod.policy_summary(settings),
                "uptime_s": round(time.time() - self.state.started_at, 1),
                "audit_entries": self.state.audit.count() if settings.get("audit", True) else 0,
                "user": getpass.getuser(),
            })
            return
        if path == "/v1/audit":
            limit = 20
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
                for part in query.split("&"):
                    if part.startswith("limit="):
                        try:
                            limit = int(part.split("=", 1)[1])
                        except ValueError:
                            limit = 20
            entries = self.state.audit.read(limit=max(0, min(limit, 500)))
            self._send(200, {"ok": True, "entries": entries, "summary": audit_mod.summarize(entries)})
            return
        self._error(404, "not found")

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        if not self._authorized():
            return
        path = self.path.split("?", 1)[0]
        if path != "/v1/exec":
            self._error(404, "not found")
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._error(400, str(exc))
            return
        acquired = self.state.semaphore.acquire(blocking=False)
        if not acquired:
            self._error(429, "too many concurrent commands")
            return
        try:
            self._exec(payload)
        finally:
            self.state.semaphore.release()

    def _exec(self, payload: Mapping[str, Any]) -> None:
        command = payload.get("command")
        if not isinstance(command, str) or not command.strip():
            self._error(400, "command must be a non-empty string")
            return
        settings = self.state.settings
        try:
            request = _parse_exec_request(command)
        except ValueError as exc:
            self._error(400, str(exc))
            return
        policy_command = request.policy_command
        if not policy_command.strip():
            self._error(400, "command is empty")
            return
        try:
            timeout = int(payload.get("timeout") or settings["timeout"])
        except (TypeError, ValueError):
            timeout = settings["timeout"]
        timeout = max(1, min(timeout, int(settings["max_timeout"])))
        stdin_data = payload.get("stdin")
        if stdin_data is not None and not isinstance(stdin_data, str):
            self._error(400, "stdin must be a string")
            return
        if stdin_data is not None and len(stdin_data.encode("utf-8", "replace")) > MAX_BODY_BYTES:
            self._error(413, "stdin exceeds the request limit")
            return

        raw_cwd = request.cwd or payload.get("cwd")
        cwd = str(raw_cwd or self.state.workspace)
        try:
            cwd_path = Path(os.path.expandvars(os.path.expanduser(cwd)))
            if not cwd_path.is_absolute():
                cwd_path = self.state.workspace / cwd_path
            cwd_path = cwd_path.resolve()
        except OSError:
            cwd_path = self.state.workspace
        if not cwd_path.is_dir():
            self._error(400, f"cwd is not a directory on the local machine: {cwd_path}")
            return

        executable = (
            _build_wrapped_command(
                policy_command,
                str(cwd_path),
                request.cwd_marker,
                request.pipe_marker,
            )
            if request.wrapped
            else policy_command
        )
        if len(executable.encode("utf-8", "replace")) > _MAX_WRAPPED_COMMAND_BYTES:
            self._error(413, "command exceeds the local execution limit")
            return

        decision = policy_mod.classify_command(
            policy_command, settings=settings, workspace=self.state.workspace, cwd=cwd_path
        )
        command_id = uuid.uuid4().hex[:12]
        client = self._client_label()
        if decision.action == "deny":
            self.state.audit.append({
                "id": command_id, "command": policy_command, "cwd": str(cwd_path),
                "decision": "deny", "reason": decision.reason, "client": client,
                "returncode": None, "duration_ms": 0, "output_bytes": 0,
            })
            self._error(403, f"Sidecar denied this command: {decision.reason}", reason=decision.reason)
            return

        approval = ""
        if decision.action == "ask":
            with self.state.lock:
                ok, why = self.state.approver(policy_command, str(cwd_path), timeout, client)
            if not ok:
                self.state.audit.append({
                    "id": command_id, "command": policy_command, "cwd": str(cwd_path),
                    "decision": "ask", "reason": why, "approval": "denied", "client": client,
                    "returncode": None, "duration_ms": 0, "output_bytes": 0,
                })
                self._error(403, f"The local user did not approve this command: {why}", reason=why)
                return
            approval = "approved"
        else:
            approval = "auto"

        started = time.monotonic()
        output = ""
        returncode = 125
        truncated = False
        timed_out = False
        try:
            env = safe_env(cwd=cwd_path)
            proc = subprocess.Popen(
                [_bash_path(), "-c", executable],
                cwd=str(cwd_path),
                env=env,
                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
            try:
                output, _ = proc.communicate(input=stdin_data, timeout=timeout)
                returncode = int(proc.returncode if proc.returncode is not None else 125)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError, OSError):
                    try:
                        proc.kill()
                    except OSError:
                        pass
                try:
                    output, _ = proc.communicate(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    output = output or ""
                returncode = 124
                output = (output or "") + f"\n[Sidecar: command timed out after {timeout}s on the local machine]"
        except FileNotFoundError:
            output = "Sidecar: the local shell could not be started."
            returncode = 127
        except Exception as exc:
            output = f"Sidecar: could not run the command locally: {exc}"
            returncode = 125
        duration_ms = int((time.monotonic() - started) * 1000)
        output, truncated = _truncate_output(output or "", int(settings["max_output_bytes"]))
        entry = self.state.audit.append({
            "id": command_id, "command": policy_command, "cwd": str(cwd_path),
            "decision": decision.action, "reason": decision.reason, "approval": approval,
            "client": client, "returncode": returncode, "duration_ms": duration_ms,
            "output_bytes": len(output.encode("utf-8", "replace")), "truncated": truncated,
        })
        self._send(200, {
            "ok": True,
            "id": command_id,
            "output": output,
            "returncode": returncode,
            "duration_ms": duration_ms,
            "decision": decision.action,
            "approval": approval,
            "truncated": truncated,
            "timed_out": timed_out,
            "audit": entry,
        })


class SidecarHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        state: ServerState,
        *,
        handler: type[BaseHTTPRequestHandler] = SidecarHandler,
    ):
        self.state = state
        super().__init__(address, handler)


def build_state(
    *,
    token: str,
    settings: Mapping[str, Any] | None = None,
    workspace: str | os.PathLike[str] | None = None,
    approver: Approver | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> ServerState:
    normalized = policy_mod.normalize_settings(settings)
    workspace_path = policy_mod.resolve_workspace(workspace or normalized["workspace"])
    normalized["workspace"] = str(workspace_path)
    data_path = Path(data_dir) if data_dir else config_mod.local_data_dir()
    return ServerState(
        token=token,
        settings=normalized,
        workspace=workspace_path,
        audit=audit_mod.AuditLog(data_path, enabled=normalized["audit"]),
        approver=approver or _terminal_approver,
        semaphore=threading.BoundedSemaphore(normalized["max_concurrent"]),
        hostname=socket.gethostname(),
        started_at=time.time(),
        lock=threading.Lock(),
    )


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    settings: Mapping[str, Any] | None = None,
    workspace: str | os.PathLike[str] | None = None,
    approver: Approver | None = None,
    data_dir: str | os.PathLike[str] | None = None,
) -> SidecarHTTPServer:
    state = build_state(
        token=token or token_mod.load_or_create_token(Path(data_dir) if data_dir else None),
        settings=settings,
        workspace=workspace,
        approver=approver,
        data_dir=data_dir,
    )
    return SidecarHTTPServer((host, int(port)), state)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str | None = None,
    settings: Mapping[str, Any] | None = None,
    workspace: str | os.PathLike[str] | None = None,
    approver: Approver | None = None,
    data_dir: str | os.PathLike[str] | None = None,
    quiet: bool = False,
) -> int:
    server = create_server(
        host=host, port=port, token=token, settings=settings,
        workspace=workspace, approver=approver, data_dir=data_dir,
    )
    state = server.state
    actual_host, actual_port = server.server_address[:2]
    if not quiet:
        print("Sidecar daemon", file=sys.stderr)
        print(f"  listening   http://{actual_host}:{actual_port}", file=sys.stderr)
        print(f"  workspace   {state.workspace}", file=sys.stderr)
        print(f"  policy      {policy_mod.policy_summary(state.settings)}", file=sys.stderr)
        print(f"  audit       {state.audit.path}", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Pair a remote Hermes with:  hermes sidecar pair", file=sys.stderr)
        print("  Keep this bound to loopback, or put it behind Tailscale/SSH.", file=sys.stderr)
        print("", file=sys.stderr)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nSidecar stopped.", file=sys.stderr)
    finally:
        server.server_close()
    return 0
