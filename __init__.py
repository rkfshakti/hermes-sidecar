"""Sidecar — remote brain, local hands.

Registers a Hermes terminal-environment provider (``terminal.backend: sidecar``),
two inspection tools, a ``/sidecar`` slash command, ``hermes sidecar``, and a
bundled skill. The remote agent keeps its own skills, memory and provider
configuration; terminal and file-tool commands travel over a paired HTTP
connection to a daemon running on the user's local machine, where the local
policy and the person at the keyboard decide what actually runs.

Imports are deliberately lazy so the plugin stays importable without Hermes and
a broken optional import cannot take down discovery.
"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path

logger = logging.getLogger(__name__)

_PLUGIN_DIR = Path(__file__).parent
_SKILL = _PLUGIN_DIR / "skills" / "sidecar" / "SKILL.md"


def _slash(raw_args: str, **kwargs) -> str:
    """Handle ``/sidecar [status|test|audit|pair]`` inside a session."""
    from . import config as config_mod
    from .client import SidecarClient, SidecarError
    from . import handlers

    try:
        parts = shlex.split(raw_args or "")
    except ValueError:
        parts = (raw_args or "").split()
    sub = (parts[0] if parts else "status").lower()
    settings = config_mod.load_settings()
    if sub in ("status", "health"):
        return handlers.status()
    if sub == "audit":
        limit = 20
        if len(parts) > 1:
            try:
                limit = int(parts[1])
            except ValueError:
                limit = 20
        return handlers.audit({"limit": limit})
    if sub == "test":
        try:
            result = SidecarClient.from_settings(settings).test()
        except SidecarError as exc:
            return f"Sidecar test failed: {exc}"
        return (
            f"Sidecar round-trip: exit={result.get('returncode')} "
            f"decision={result.get('decision')} duration={result.get('duration_ms')}ms\n"
            f"{str(result.get('output') or '').strip()}"
        )
    if sub in ("pair", "token"):
        return (
            "Sidecar pairing is local-machine only. On the local machine run:\n"
            "  hermes sidecar pair\n"
            "It prints the URL, token and the remote `hermes config set` commands. "
            "The token is not printed in a chat session because chat transcripts are stored."
        )
    return "usage: /sidecar [status|test|audit [limit]|pair]"


def register(ctx) -> None:
    """Wire the provider, tools, commands and skill into Hermes."""
    from . import config as config_mod
    from . import handlers, schemas
    from .cli import register_cli, sidecar_command
    from .provider import SidecarProvider

    settings = config_mod.load_settings
    provider = SidecarProvider(settings=settings)
    ctx.register_terminal_environment_provider(provider)

    ctx.register_tool(
        name="sidecar_status",
        toolset="sidecar",
        schema=schemas.SIDECAR_STATUS,
        handler=handlers.status,
        emoji="🛰️",
    )
    ctx.register_tool(
        name="sidecar_audit",
        toolset="sidecar",
        schema=schemas.SIDECAR_AUDIT,
        handler=handlers.audit,
        emoji="📋",
    )

    ctx.register_command(
        "sidecar",
        handler=_slash,
        description="Inspect the paired local execution daemon, test it, or read its audit log.",
        args_hint="status|test|audit [limit]|pair",
    )
    ctx.register_cli_command(
        name="sidecar",
        help="Remote brain, local hands: paired local execution for Hermes",
        setup_fn=register_cli,
        handler_fn=sidecar_command,
        description=(
            "Run the local Sidecar daemon, pair a remote Hermes, inspect its policy and audit "
            "log, and verify the bridge end to end."
        ),
    )

    try:
        if _SKILL.exists():
            ctx.register_skill("sidecar", _SKILL)
    except Exception:
        logger.debug("Sidecar skill registration failed", exc_info=True)
