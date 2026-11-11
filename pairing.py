"""Pairing tokens for the Sidecar daemon.

The token is a bearer credential for the local HTTP API. It is generated on the
local machine, stored with mode 0600 under the plugin data directory, and only
ever sent to the daemon the user configured. It is not a provider credential and
is never read from another tool's credential store.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path


def data_dir() -> Path:
    """The profile-scoped plugin data directory, with a no-Hermes fallback."""
    try:
        from plugins.plugin_storage import plugin_data_dir

        return Path(plugin_data_dir("sidecar"))
    except Exception:
        root = os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")
        return Path(root) / "plugin-data" / "sidecar"


def token_path(root: Path | None = None) -> Path:
    return (Path(root) if root else data_dir()) / "token"


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def read_token(root: Path | None = None) -> str:
    path = token_path(root)
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except OSError:
        return ""


def write_token(token: str, root: Path | None = None) -> Path:
    path = token_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    tmp = path.with_suffix(".tmp")
    tmp.write_text(token.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)
    return path


def load_or_create_token(root: Path | None = None) -> str:
    token = read_token(root)
    if token:
        return token
    token = generate_token()
    write_token(token, root)
    return token


def rotate_token(root: Path | None = None) -> str:
    token = generate_token()
    write_token(token, root)
    return token


def tokens_equal(candidate: str, expected: str) -> bool:
    """Constant-time comparison that also hides length differences."""
    if not candidate or not expected:
        return False
    left = hashlib.sha256(candidate.encode("utf-8", "replace")).digest()
    right = hashlib.sha256(expected.encode("utf-8", "replace")).digest()
    return hmac.compare_digest(left, right)


def mask_token(token: str) -> str:
    if not token:
        return "(not set)"
    if len(token) <= 10:
        return token[:2] + "…" + token[-2:]
    return token[:4] + "…" + token[-4:]
