"""Handlers for the Sidecar inspection tools."""

from __future__ import annotations

import json
from typing import Any, Mapping

from . import config as config_mod
from .client import SidecarClient, SidecarError


def _client() -> SidecarClient:
    return SidecarClient.from_settings(config_mod.load_settings())


def status(args: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
    settings = config_mod.load_settings()
    payload: dict[str, Any] = {
        "ok": False,
        "url": settings["url"],
        "token": "set" if settings["token"] else "missing",
        "workspace": config_mod.expanded_workspace(settings["workspace"]),
        "timeout": settings["timeout"],
    }
    try:
        health = _client().health(timeout=2.5)
        payload.update({
            "ok": True,
            "version": health.get("version"),
            "hostname": health.get("hostname"),
            "platform": health.get("platform"),
            "user": health.get("user"),
            "local_workspace": health.get("workspace"),
            "approval": health.get("approval"),
            "policy": health.get("policy"),
            "audit_entries": health.get("audit_entries", 0),
        })
    except SidecarError as exc:
        payload["error"] = str(exc)
    return json.dumps(payload, indent=2)


def audit(args: Mapping[str, Any] | None = None, **kwargs: Any) -> str:
    data = dict(args or {})
    try:
        limit = int(data.get("limit") or 20)
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 200))
    try:
        entries = _client().audit(limit=limit)
    except SidecarError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, indent=2)
    slim = []
    for entry in entries:
        slim.append({
            "ts": entry.get("ts"),
            "command": entry.get("command"),
            "cwd": entry.get("cwd"),
            "decision": entry.get("decision"),
            "approval": entry.get("approval"),
            "returncode": entry.get("returncode"),
            "duration_ms": entry.get("duration_ms"),
            "reason": entry.get("reason"),
        })
    return json.dumps({"ok": True, "entries": slim, "count": len(slim)}, indent=2)
