"""HTTP client for the Sidecar daemon.

Standard library only: the plugin has no third-party dependencies, so installing
it cannot move Hermes's dependency pins.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from . import config as config_mod

DEFAULT_CONNECT_TIMEOUT = 10.0


class SidecarError(RuntimeError):
    """A daemon/transport failure with a user-actionable message."""

    def __init__(self, message: str, *, status: int = 0, reason: str = "", detail: str = ""):
        super().__init__(message)
        self.status = int(status or 0)
        self.reason = reason
        self.detail = detail


def _normalize_url(url: str) -> str:
    value = (url or "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ("http", "https"):
        raise SidecarError("Sidecar URL must start with http:// or https://")
    if not parsed.netloc:
        raise SidecarError("Sidecar URL is missing a host")
    return value


class SidecarClient:
    def __init__(
        self,
        url: str | None = None,
        token: str | None = None,
        *,
        timeout: float = DEFAULT_CONNECT_TIMEOUT,
        workspace: str | None = None,
    ):
        settings = config_mod.load_settings()
        self.url = _normalize_url(url or settings["url"])
        self.token = (token if token is not None else settings["token"]) or ""
        self.timeout = float(timeout)
        self.workspace = workspace or settings["workspace"]
        self._resolved_workspace = ""

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any] | None = None) -> "SidecarClient":
        data = dict(settings or config_mod.load_settings())
        return cls(
            str(data.get("url") or config_mod.DEFAULT_URL),
            str(data.get("token") or ""),
            workspace=str(data.get("workspace") or config_mod.DEFAULT_WORKSPACE),
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        if not self.token:
            raise SidecarError(
                "Sidecar is not paired: no token is configured. On the local machine run "
                "`hermes sidecar pair`, then set the token on the remote profile."
            )
        body = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "hermes-sidecar/1.0",
        }
        headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.url + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
                if not raw:
                    return {}
                value = json.loads(raw.decode("utf-8", "replace"))
                return value if isinstance(value, dict) else {"value": value}
        except urllib.error.HTTPError as exc:
            detail = ""
            reason = ""
            try:
                raw = exc.read().decode("utf-8", "replace")
                parsed = json.loads(raw) if raw else {}
                if isinstance(parsed, dict):
                    detail = str(parsed.get("error") or parsed.get("detail") or "")
                    reason = str(parsed.get("reason") or "")
            except Exception:
                detail = ""
            message = detail or f"Sidecar daemon returned HTTP {exc.code}"
            if exc.code == 401:
                message = (
                    "Sidecar rejected the pairing token (HTTP 401). Run `hermes sidecar pair` "
                    "on the local machine and update the remote token."
                )
            elif exc.code == 403:
                message = detail or "The local user denied this command."
            elif exc.code == 429:
                message = "Sidecar is busy with too many concurrent commands; retry shortly."
            raise SidecarError(message, status=exc.code, reason=reason, detail=detail) from None
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, (socket.timeout, TimeoutError)):
                raise SidecarError(
                    f"Sidecar at {self.url} did not answer in time. The local daemon may be "
                    "busy, blocked on an approval prompt, or unreachable."
                ) from None
            raise SidecarError(
                f"Cannot reach the Sidecar daemon at {self.url}. Is `hermes sidecar serve` "
                f"running on the local machine, and is the URL/tunnel correct? ({reason})"
            ) from None
        except (socket.timeout, TimeoutError):
            raise SidecarError(
                f"Sidecar at {self.url} did not answer in time. The local daemon may be busy "
                "or blocked on an approval prompt."
            ) from None
        except json.JSONDecodeError:
            raise SidecarError("Sidecar returned a non-JSON response; is the URL pointing at the daemon?") from None

    def health(self, *, timeout: float = 2.0) -> dict[str, Any]:
        return self._request("GET", "/v1/health", timeout=timeout)

    def local_workspace(self, *, timeout: float = 2.0) -> str:
        """The daemon's absolute workspace, resolving ``~`` on the local side.

        The remote process's home is not the local home, so a configured ``~``
        must never be expanded here. Ask the daemon once and cache the answer.
        """
        workspace = str(self.workspace or "").strip()
        if workspace and not workspace.startswith("~") and os.path.isabs(workspace):
            return workspace
        if self._resolved_workspace:
            return self._resolved_workspace
        try:
            health = self.health(timeout=timeout)
        except SidecarError:
            return ""
        resolved = str(health.get("workspace") or "").strip()
        if resolved:
            self._resolved_workspace = resolved
        return resolved

    def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
        stdin: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "command": command,
            "timeout": int(timeout or config_mod.load_settings()["timeout"]),
        }
        target = cwd or self.local_workspace()
        if target:
            payload["cwd"] = target
        if stdin is not None:
            payload["stdin"] = stdin
        return self._request("POST", "/v1/exec", payload, timeout=float(payload["timeout"]) + 15.0)

    def audit(self, limit: int = 20) -> list[dict[str, Any]]:
        value = self._request("GET", f"/v1/audit?limit={max(0, min(int(limit), 500))}")
        entries = value.get("entries")
        return [item for item in entries if isinstance(item, dict)] if isinstance(entries, list) else []

    def test(self) -> dict[str, Any]:
        """Round-trip a harmless command through the real exec path."""
        return self.execute("printf 'sidecar ok\\n'", timeout=15)
