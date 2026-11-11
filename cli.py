"""``hermes sidecar`` CLI: serve, pair, status, test, log, demo, verify."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from . import audit as audit_mod
from . import config as config_mod
from . import policy as policy_mod
from . import pairing as token_mod

_ANSI = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _ANSI else text


def _ok(text: str) -> str:
    return _c("32", text)


def _bad(text: str) -> str:
    return _c("31", text)


def _dim(text: str) -> str:
    return _c("2", text)


def _bold(text: str) -> str:
    return _c("1", text)


def _data_dir() -> Path:
    return config_mod.local_data_dir()


def _settings() -> dict[str, Any]:
    return config_mod.load_settings()


def _enabled() -> bool:
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly() or {}
        enabled = (config.get("plugins") or {}).get("enabled") or []
        return any(str(item).split("/")[-1] == "sidecar" for item in enabled)
    except Exception:
        return False


def _active_backend() -> str:
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly() or {}
        return str(((config.get("terminal") or {}).get("backend") or "")).strip()
    except Exception:
        return ""


def _remote_client():
    from .client import SidecarClient

    return SidecarClient.from_settings(_settings())


def _warn_transport(url: str) -> None:
    """Warn when a non-loopback daemon is addressed over plain HTTP."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in ("127.0.0.1", "localhost", "::1"):
        print(_bad("WARNING: this daemon URL is plain HTTP and not loopback."), file=sys.stderr)
        print("  The pairing token and command output would travel in cleartext.", file=sys.stderr)
        print("  Use an SSH tunnel or Tailscale, or put a TLS terminator in front.", file=sys.stderr)
        print("", file=sys.stderr)


# ---------------------------------------------------------------------------
# serve
# ---------------------------------------------------------------------------

def _cmd_serve(args: argparse.Namespace) -> int:
    from . import daemon

    root = _data_dir()
    token = token_mod.rotate_token(root) if getattr(args, "rotate_token", False) else token_mod.load_or_create_token(root)
    workspace = str(getattr(args, "workspace", None) or os.getcwd())
    settings = {
        "approval": getattr(args, "approval", policy_mod.DEFAULT_APPROVAL),
        "timeout": getattr(args, "timeout", policy_mod.DEFAULT_TIMEOUT),
        "max_timeout": getattr(args, "max_timeout", policy_mod.DEFAULT_MAX_TIMEOUT),
        "workspace": workspace,
        "allow": getattr(args, "allow", None) or [],
        "deny": getattr(args, "deny", None) or [],
        "allow_outside_workspace": bool(getattr(args, "allow_outside_workspace", False)),
        "audit": not bool(getattr(args, "no_audit", False)),
    }
    host = str(getattr(args, "host", "127.0.0.1") or "127.0.0.1")
    port = int(getattr(args, "port", 8765) or 8765)
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(_bad("WARNING: Sidecar is binding to a non-loopback address."), file=sys.stderr)
        print("  Anyone who can reach this port and knows the token can run commands as you.", file=sys.stderr)
        print("  Prefer Tailscale or an SSH tunnel, and never expose it to the public internet.", file=sys.stderr)
        print("", file=sys.stderr)
    return int(daemon.serve(
        host=host,
        port=port,
        token=token,
        settings=settings,
        workspace=workspace,
        quiet=bool(getattr(args, "quiet", False)),
    ) or 0)


# ---------------------------------------------------------------------------
# pair
# ---------------------------------------------------------------------------

def _pair_payload(url: str, token: str, workspace: str | None = None) -> dict[str, Any]:
    local_workspace = workspace or str(config_mod.expanded_workspace(_settings().get("workspace")))
    commands = [
        "hermes plugins install rkfshakti/hermes-sidecar",
        "hermes plugins enable sidecar",
        "hermes config set terminal.backend sidecar",
        f"hermes config set plugins.entries.sidecar.settings.url {url}",
        f"hermes config set plugins.entries.sidecar.settings.token {token}",
        f"hermes config set plugins.entries.sidecar.settings.workspace {local_workspace}",
        "hermes sidecar test",
    ]
    return {"url": url, "token": token, "workspace": local_workspace, "commands": commands}


def _cmd_pair(args: argparse.Namespace) -> int:
    root = _data_dir()
    token = token_mod.rotate_token(root) if getattr(args, "rotate", False) else token_mod.load_or_create_token(root)
    url = str(getattr(args, "url", "") or "http://127.0.0.1:8765").rstrip("/")
    _warn_transport(url)
    payload = _pair_payload(url, token, getattr(args, "workspace", "") or None)
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0
    if getattr(args, "env", False):
        print(f"export SIDECAR_URL={shlex.quote(url)}")
        print(f"export SIDECAR_TOKEN={shlex.quote(token)}")
        return 0
    print(_bold("Sidecar pairing"))
    print("───────────────")
    print(f"  Local daemon   {url}")
    print(f"  Token          {token_mod.mask_token(token)}  (full token below)")
    print(f"  Workspace      {config_mod.expanded_workspace(_settings().get('workspace'))}")
    print()
    print(_bold("On this local machine"))
    print("  hermes sidecar serve")
    print()
    print(_bold("On the remote Hermes"))
    for command in payload["commands"]:
        print(f"  {command}")
    print()
    print(_dim("The token is a bearer credential. Prefer the environment on the remote host:"))
    print(_dim(f"  export SIDECAR_URL={shlex.quote(url)}"))
    print(_dim(f"  export SIDECAR_TOKEN={shlex.quote(token)}"))
    print()
    print(_dim("If the remote host is not this machine, reach the daemon through Tailscale or an"))
    print(_dim("SSH tunnel. Never expose the port directly to the public internet."))
    return 0


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

def _cmd_status(args: argparse.Namespace) -> int:
    settings = _settings()
    _warn_transport(str(settings.get("url") or ""))
    payload: dict[str, Any] = {
        "backend": _active_backend(),
        "plugin_enabled": _enabled(),
        "url": settings["url"],
        "token": token_mod.mask_token(settings["token"]),
        "workspace": config_mod.expanded_workspace(settings["workspace"]),
        "timeout": settings["timeout"],
        "data_dir": str(_data_dir()),
        "health": None,
        "error": "",
    }
    try:
        payload["health"] = _remote_client().health(timeout=2.5)
        local_workspace = str(payload["health"].get("workspace") or "").strip()
        if local_workspace:
            payload["workspace"] = local_workspace
    except Exception as exc:
        payload["error"] = str(exc)
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2))
        return 0 if payload["health"] else 1
    print(_bold("Sidecar"))
    print("────────")
    print(f"  Backend        {payload['backend'] or '(unset)'}"
          f"{'  ✓' if payload['backend'] == 'sidecar' else ''}")
    print(f"  Plugin         {'enabled' if payload['plugin_enabled'] else 'not enabled'}")
    print(f"  Remote URL     {payload['url']}")
    print(f"  Token          {payload['token']}")
    print(f"  Workspace      {payload['workspace']}")
    health = payload["health"]
    if health:
        print(f"  Daemon         {_ok('reachable')} · {health.get('version')} · {health.get('platform')}")
        print(f"  Local policy   {health.get('policy')}")
        print(f"  Local user     {health.get('user')} @ {health.get('hostname')}")
        print(f"  Audit          {health.get('audit_entries', 0)} commands recorded")
    else:
        print(f"  Daemon         {_bad('unreachable')}")
        print(f"  {payload['error']}")
        return 1
    if payload["backend"] != "sidecar":
        print()
        print(_dim("Activate the backend with: hermes config set terminal.backend sidecar"))
    return 0


# ---------------------------------------------------------------------------
# test / log
# ---------------------------------------------------------------------------

def _cmd_test(args: argparse.Namespace) -> int:
    try:
        result = _remote_client().test()
    except Exception as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            print(_bad(f"Sidecar test failed: {exc}"))
        return 1
    ok = int(result.get("returncode") or 0) == 0 and "sidecar ok" in str(result.get("output") or "")
    if getattr(args, "json", False):
        print(json.dumps({"ok": ok, **result}, indent=2))
    else:
        print(_bold("Sidecar round-trip test"))
        print("─────────────────────────")
        print(f"  output       {str(result.get('output') or '').strip()}")
        print(f"  exit code    {result.get('returncode')}")
        print(f"  duration     {result.get('duration_ms')} ms")
        print(f"  decision     {result.get('decision')} ({result.get('approval')})")
        print(_ok("  PASS") if ok else _bad("  FAIL"))
    return 0 if ok else 1


def _cmd_log(args: argparse.Namespace) -> int:
    limit = int(getattr(args, "limit", 20) or 20)
    local = bool(getattr(args, "local", False))
    entries: list[dict[str, Any]] = []
    if local:
        entries = audit_mod.AuditLog(_data_dir()).read(limit=limit)
    else:
        try:
            entries = _remote_client().audit(limit=limit)
        except Exception as exc:
            if not getattr(args, "json", False):
                print(_bad(f"Could not fetch the remote audit: {exc}"))
                print(_dim("Use --local to read this machine's audit log."))
            else:
                print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return 1
    if getattr(args, "json", False):
        print(json.dumps({"ok": True, "entries": entries, "summary": audit_mod.summarize(entries)}, indent=2))
        return 0
    print(audit_mod.render_text(entries, limit=limit))
    return 0


# ---------------------------------------------------------------------------
# demo / verify
# ---------------------------------------------------------------------------

def _start_test_server(*, settings: dict[str, Any], workspace: Path, approver=None, token: str = "test-token"):
    from . import daemon

    server = daemon.create_server(
        host="127.0.0.1",
        port=0,
        token=token,
        settings=settings,
        workspace=workspace,
        approver=approver,
        data_dir=workspace / ".sidecar-data",
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, thread, f"http://{host}:{port}", token


def _stop_server(server, thread) -> None:
    try:
        server.shutdown()
        server.server_close()
    finally:
        thread.join(timeout=3)


def _demo_lines() -> list[tuple[str, str, int]]:
    return [
        ("pwd", "where am I?", 0),
        ("printf 'hello from the local machine\\n'", "a local command returns output", 0),
        ("printf 'written on the local disk\\n' > sidecar-demo.txt", "write a file on the local disk", 0),
        ("cat sidecar-demo.txt", "read it back", 0),
        ("sh -c 'exit 7'", "exit codes survive the bridge", 7),
        ("osascript -e 'return 1'", "the deny list stops Apple Events automation", 125),
    ]


def _cmd_demo(args: argparse.Namespace) -> int:
    from .client import SidecarClient

    workspace = Path(tempfile.mkdtemp(prefix="sidecar-demo-"))
    settings = {
        "approval": "allow",
        "workspace": str(workspace),
        "timeout": 30,
        "audit": True,
        "max_concurrent": 2,
    }
    server, thread, url, token = _start_test_server(settings=settings, workspace=workspace)
    rows: list[dict[str, Any]] = []
    try:
        client = SidecarClient(url, token, workspace=str(workspace))
        for command, label, expected_rc in _demo_lines():
            started = time.monotonic()
            try:
                result = client.execute(command, cwd=str(workspace), timeout=20)
                actual_rc = int(result.get("returncode") if result.get("returncode") is not None else 125)
                ok = actual_rc == expected_rc
                rows.append({
                    "command": command, "label": label, "ok": ok,
                    "output": str(result.get("output") or "").strip(),
                    "returncode": actual_rc,
                    "decision": result.get("decision"),
                    "approval": result.get("approval"),
                    "duration_ms": result.get("duration_ms") or int((time.monotonic() - started) * 1000),
                })
            except Exception as exc:
                denied_as_expected = expected_rc != 0 and command.startswith("sudo")
                rows.append({
                    "command": command, "label": label, "ok": denied_as_expected,
                    "output": str(exc), "returncode": 125, "decision": "deny",
                    "approval": "", "duration_ms": int((time.monotonic() - started) * 1000),
                })
    finally:
        _stop_server(server, thread)
    if getattr(args, "json", False):
        print(json.dumps({"ok": all(row["ok"] for row in rows), "workspace": str(workspace), "rows": rows}, indent=2))
        return 0 if all(row["ok"] for row in rows) else 1
    print(_bold("Sidecar demo"))
    print("─────────────")
    print(f"  local workspace  {workspace}")
    print(f"  transport        {url}")
    print()
    for row in rows:
        mark = _ok("✓") if row["ok"] else _bad("✗")
        print(f"  {mark} {row['command']}")
        print(f"    {_dim(row['label'])}")
        if row.get("output"):
            first = row["output"].splitlines()[0][:150]
            print(f"    → {first}")
        detail = f"exit={row.get('returncode')} decision={row.get('decision')} {row.get('duration_ms')}ms"
        print(f"    {_dim(detail)}")
    print()
    print(_ok("All demo checks passed." if all(row["ok"] for row in rows) else "One or more demo checks failed."))
    print(_dim(f"Audit: {workspace / '.sidecar-data' / 'audit.jsonl'}"))
    return 0 if all(row["ok"] for row in rows) else 1


def _cmd_verify(args: argparse.Namespace) -> int:
    from . import daemon
    from .client import SidecarClient, SidecarError

    checks: list[dict[str, Any]] = []

    def check(name: str, fn) -> None:
        try:
            ok, detail = fn()
        except Exception as exc:
            ok, detail = False, str(exc)
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)})

    if getattr(args, "remote", False):
        settings = _settings()
        client = SidecarClient.from_settings(settings)
        check("daemon reachable", lambda: (True, client.health().get("version", "?")))
        check("round-trip command", lambda: (client.test().get("returncode") == 0, client.test().get("output", "").strip()))
        check("audit readable", lambda: (True, f"{len(client.audit(5))} recent entries"))
    else:
        workspace = Path(tempfile.mkdtemp(prefix="sidecar-verify-"))
        settings = {"approval": "allow", "workspace": str(workspace), "timeout": 3, "audit": True, "max_concurrent": 2}
        server, thread, url, token = _start_test_server(settings=settings, workspace=workspace, token="verify-token")
        try:
            client = SidecarClient(url, token, workspace=str(workspace))
            check("daemon health", lambda: (client.health().get("ok") is True, client.health().get("version", "?")))
            check("token accepted", lambda: (client.execute("printf ok").get("returncode") == 0, "exec round-trip"))
            check("wrong token rejected", lambda: _expect_401(url, "wrong-token"))
            check("exit code preserved", lambda: (client.execute("sh -c 'exit 7'").get("returncode") == 7, "exit=7"))
            check("deny list blocks GUI automation", lambda: _expect_403(client, "osascript -e 'return 1'"))
            check("workspace escape blocked", lambda: _expect_403(client, "pwd", cwd="/tmp"))
            check("timeout enforced", lambda: _expect_timeout(client, "sleep 3", 1))
            check("audit recorded", lambda: (len(client.audit(10)) >= 3, f"{len(client.audit(10))} entries"))
        finally:
            _stop_server(server, thread)
    ok = all(item["ok"] for item in checks)
    if getattr(args, "json", False):
        print(json.dumps({"ok": ok, "checks": checks}, indent=2))
        return 0 if ok else 1
    print(_bold("Sidecar self-test"))
    print("───────────────────")
    for item in checks:
        mark = _ok("✓") if item["ok"] else _bad("✗")
        print(f"  {mark} {item['name']:<26} {_dim(item['detail'][:110])}")
    print()
    print(_ok("All checks passed.") if ok else _bad("One or more checks failed."))
    return 0 if ok else 1


def _expect_401(url: str, token: str) -> tuple[bool, str]:
    from .client import SidecarClient, SidecarError

    try:
        SidecarClient(url, token, workspace="/tmp").health(timeout=2)
        return False, "wrong token was accepted"
    except SidecarError as exc:
        return (exc.status == 401, f"HTTP {exc.status}")


def _expect_403(client, command: str, cwd: str | None = None) -> tuple[bool, str]:
    from .client import SidecarError

    try:
        result = client.execute(command, cwd=cwd, timeout=5)
        return (int(result.get("returncode") or 0) != 0, f"exit={result.get('returncode')}")
    except SidecarError as exc:
        return (exc.status == 403, f"HTTP {exc.status}: {exc}")


def _expect_timeout(client, command: str, timeout: int) -> tuple[bool, str]:
    result = client.execute(command, timeout=timeout)
    return (int(result.get("returncode") or 0) == 124, f"exit={result.get('returncode')}")


# ---------------------------------------------------------------------------
# argparse wiring
# ---------------------------------------------------------------------------

def register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="sidecar_command")
    serve = subs.add_parser("serve", help="Run the local Sidecar daemon")
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: loopback)")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--workspace", default="", help="Local workspace the agent may use")
    serve.add_argument("--approval", choices=list(policy_mod.APPROVAL_MODES), default=policy_mod.DEFAULT_APPROVAL)
    serve.add_argument("--timeout", type=int, default=policy_mod.DEFAULT_TIMEOUT)
    serve.add_argument("--max-timeout", type=int, default=policy_mod.DEFAULT_MAX_TIMEOUT)
    serve.add_argument("--allow", action="append", default=[], help="Extra allow regex")
    serve.add_argument("--deny", action="append", default=[], help="Extra deny regex")
    serve.add_argument("--allow-outside-workspace", action="store_true")
    serve.add_argument("--no-audit", action="store_true")
    serve.add_argument("--quiet", action="store_true", help="Suppress the startup banner")
    serve.add_argument("--rotate-token", action="store_true", help="Rotate the pairing token before serving")

    pair = subs.add_parser("pair", help="Print the pairing token and remote setup commands")
    pair.add_argument("--url", default="http://127.0.0.1:8765")
    pair.add_argument("--workspace", default="", help="Local workspace to print in the remote setup commands")
    pair.add_argument("--rotate", action="store_true")
    pair.add_argument("--json", action="store_true")
    pair.add_argument("--env", action="store_true", help="Print export lines only")

    status = subs.add_parser("status", help="Show remote config and local daemon health")
    status.add_argument("--json", action="store_true")

    test = subs.add_parser("test", help="Round-trip a harmless command through the daemon")
    test.add_argument("--json", action="store_true")

    log = subs.add_parser("log", help="Show the local or remote audit log")
    log.add_argument("--limit", type=int, default=20)
    log.add_argument("--json", action="store_true")
    log.add_argument("--local", action="store_true", help="Read this machine's audit log")

    demo = subs.add_parser("demo", help="Run a self-contained transport/backend demonstration")
    demo.add_argument("--json", action="store_true")

    verify = subs.add_parser("verify", help="Run the Sidecar self-test")
    verify.add_argument("--json", action="store_true")
    verify.add_argument("--remote", action="store_true", help="Test the configured remote daemon instead of a local ephemeral one")

    subparser.set_defaults(func=sidecar_command)


_DISPATCH = {
    "serve": _cmd_serve,
    "pair": _cmd_pair,
    "status": _cmd_status,
    "test": _cmd_test,
    "log": _cmd_log,
    "demo": _cmd_demo,
    "verify": _cmd_verify,
}


def sidecar_command(args: argparse.Namespace) -> int:
    sub = getattr(args, "sidecar_command", None)
    if not sub:
        print("usage: hermes sidecar {serve,pair,status,test,log,demo,verify}")
        return 2
    handler = _DISPATCH.get(sub)
    if handler is None:
        print(f"unknown subcommand: {sub}")
        return 2
    return int(handler(args) or 0)
