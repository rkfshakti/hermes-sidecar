"""Configuration helpers shared by the plugin, the CLI and the daemon.

Remote-side settings live in ``plugins.entries.sidecar.settings`` (or the
``SIDECAR_URL`` / ``SIDECAR_TOKEN`` environment variables). Local daemon settings
are CLI flags and deliberately do not come from the remote profile: a remote
agent must never be able to change the approval policy of the machine it is
asking.
"""

from __future__ import annotations

import os
import os.path
from pathlib import Path
from typing import Any, Mapping

from . import pairing as token_mod

DEFAULT_URL = "http://127.0.0.1:8765"
DEFAULT_TIMEOUT = 300
DEFAULT_WORKSPACE = "~"

_PLUGIN_ID = "sidecar"
_SETTINGS_KEY = ("plugins", "entries", _PLUGIN_ID, "settings")


def _config_dict() -> dict[str, Any]:
    try:
        from hermes_cli.config import load_config_readonly

        value = load_config_readonly() or {}
        return dict(value) if isinstance(value, Mapping) else {}
    except Exception:
        return {}


def _walk(data: Mapping[str, Any], keys: tuple[str, ...]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def raw_settings() -> dict[str, Any]:
    value = _walk(_config_dict(), _SETTINGS_KEY)
    return dict(value) if isinstance(value, Mapping) else {}


def _secret_env(name: str, default: str = "") -> str:
    try:
        from agent.secret_scope import get_secret

        value = get_secret(name, default)
        return str(value or default).strip()
    except Exception:
        return str(os.environ.get(name, default) or default).strip()


def load_settings() -> dict[str, Any]:
    raw = raw_settings()
    url = str(raw.get("url") or os.environ.get("SIDECAR_URL") or DEFAULT_URL).strip() or DEFAULT_URL
    token = str(raw.get("token") or "").strip()
    if not token:
        token = _secret_env("SIDECAR_TOKEN")
    workspace = str(raw.get("workspace") or os.environ.get("SIDECAR_WORKSPACE") or DEFAULT_WORKSPACE).strip() or DEFAULT_WORKSPACE
    try:
        timeout = int(raw.get("timeout") or os.environ.get("SIDECAR_TIMEOUT") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    return {
        "url": url,
        "token": token,
        "workspace": workspace,
        "timeout": max(1, min(timeout, 3600)),
    }


def remote_ready() -> bool:
    settings = load_settings()
    return bool(settings["url"] and settings["token"])


def local_data_dir() -> Path:
    return token_mod.data_dir()


def local_token() -> str:
    return token_mod.read_token(local_data_dir())


def expanded_workspace(value: str | os.PathLike[str] | None = None) -> Path:
    text = str(value or load_settings()["workspace"] or DEFAULT_WORKSPACE)
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def masked(settings: Mapping[str, Any] | None = None) -> dict[str, Any]:
    data = dict(settings or load_settings())
    data["token"] = token_mod.mask_token(str(data.get("token") or ""))
    return data
