#!/usr/bin/env python3
"""A tiny stand-in for the remote Hermes agent in the Sidecar demo.

It sends the same requests the Sidecar terminal backend sends; the point is the
round trip and the local approval prompt, not the model.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sidecar.client import SidecarClient, SidecarError  # noqa: E402


def _token() -> str:
    token = os.environ.get("SIDECAR_TOKEN", "").strip()
    if token:
        return token
    profile = os.environ.get("SIDECAR_DEMO_PROFILE", "sidecar-test")
    path = Path.home() / ".hermes" / "profiles" / profile / "plugin-data" / "sidecar" / "token"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def line(text: str = "") -> None:
    print(text, flush=True)


def main() -> int:
    url = os.environ.get("SIDECAR_URL", "http://127.0.0.1:8798")
    token = _token()
    workspace = os.environ.get("SIDECAR_WORKSPACE", os.getcwd())
    client = SidecarClient(url, token, workspace=workspace)
    line("\033[1mremote Hermes\033[0m  ·  brain on the VPS")
    line(f"local hands     {workspace}")
    line(f"transport       {url}")
    line()
    time.sleep(1.0)
    commands = [
        ("pwd", "where am I?"),
        ("ls -1 | head -6", "list the local workspace"),
        ("cat README.md | head -4", "read a local file"),
        ("printf 'local write\\n' > demo.txt", "write a local file"),
        ("cat demo.txt", "read it back"),
        ("osascript -e 'return 1'", "try an Apple Events escape hatch"),
    ]
    for command, label in commands:
        line(f"\033[36m$ {command}\033[0m")
        line(f"  \033[2m{label}\033[0m")
        started = time.monotonic()
        try:
            result = client.execute(command, cwd=workspace, timeout=60)
            output = str(result.get("output") or "").rstrip()
            if output:
                for row in output.splitlines()[:8]:
                    line(f"  {row}")
            line(
                f"  \033[2m[exit {result.get('returncode')} · {result.get('decision')} · "
                f"{result.get('duration_ms')}ms]\033[0m"
            )
        except SidecarError as exc:
            line(f"  \033[31m[blocked] {exc}\033[0m")
            line(f"  \033[2m[{int((time.monotonic() - started) * 1000)}ms]\033[0m")
        line()
        time.sleep(0.7)
    line("\033[32mDone. Every decision is in the local audit log.\033[0m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
