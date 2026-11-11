"""Hermes terminal-environment provider for Sidecar.

``terminal.backend: sidecar`` makes every terminal and file-tool command travel
over the paired HTTP connection to the local daemon. The daemon applies the local
policy and returns the output; from Hermes's point of view this is just another
remote backend, like SSH or a container.
"""

from __future__ import annotations

import base64
import os
import threading
from pathlib import Path
from typing import Any, Callable, Mapping

from . import config as config_mod
from .client import SidecarClient, SidecarError

try:  # Imported only inside a real Hermes process; tests can import the module standalone.
    from agent.terminal_env_provider import TerminalEnvironmentProvider
    from tools.environments.base import BaseEnvironment
except Exception:  # pragma: no cover - exercised by standalone unit tests
    TerminalEnvironmentProvider = object  # type: ignore[assignment,misc]
    BaseEnvironment = object  # type: ignore[assignment,misc]


class _RemoteProcessHandle:
    """A ``ProcessHandle`` backed by one blocking HTTP request.

    ``BaseEnvironment`` expects ``poll``/``kill``/``wait`` plus a readable
    ``stdout``. A worker thread performs the request and writes the returned
    output into a pipe, so the normal drain/wait machinery is reused unchanged.
    """

    def __init__(self, exec_fn: Callable[[], tuple[str, int]], cancel_fn: Callable[[], None] | None = None):
        self._exec_fn = exec_fn
        self._cancel_fn = cancel_fn
        self._done = threading.Event()
        self._returncode: int | None = None
        self._cancelled = False
        read_fd, write_fd = os.pipe()
        self._stdout = os.fdopen(read_fd, "r", encoding="utf-8-sig", errors="replace")
        self._write_fd = write_fd

        def _worker() -> None:
            try:
                output, exit_code = self._exec_fn()
                self._returncode = int(exit_code)
                try:
                    os.write(self._write_fd, (output or "").encode("utf-8", "replace"))
                except OSError:
                    pass
            except SidecarError as exc:
                self._returncode = 125
                try:
                    os.write(self._write_fd, f"[sidecar] {exc}\n".encode("utf-8", "replace"))
                except OSError:
                    pass
            except Exception as exc:  # never let a worker die silently
                self._returncode = 125
                try:
                    os.write(self._write_fd, f"[sidecar] local bridge failed: {exc}\n".encode("utf-8", "replace"))
                except OSError:
                    pass
            finally:
                try:
                    os.close(self._write_fd)
                except OSError:
                    pass
                self._done.set()

        threading.Thread(target=_worker, name="sidecar-exec", daemon=True).start()

    @property
    def stdout(self):
        return self._stdout

    @property
    def returncode(self) -> int | None:
        return self._returncode

    def poll(self) -> int | None:
        return self._returncode if self._done.is_set() else None

    def kill(self) -> None:
        self._cancelled = True
        if self._cancel_fn is not None:
            try:
                self._cancel_fn()
            except Exception:
                pass

    def wait(self, timeout: float | None = None) -> int:
        self._done.wait(timeout=timeout)
        return int(self._returncode if self._returncode is not None else 125)


class SidecarEnvironment(BaseEnvironment):  # type: ignore[misc,valid-type]
    """Run commands through the paired Sidecar daemon."""

    uses_host_filesystem = False
    is_local = False
    _passwordless_sudo_probe_supported = False

    def __init__(
        self,
        *,
        client: SidecarClient,
        workspace: str,
        timeout: int,
        task_id: str = "default",
        settings: Mapping[str, Any] | None = None,
    ):
        self.client = client
        self.workspace = str(workspace or "~")
        self.task_id = task_id or "default"
        self._settings = dict(settings or {})
        self._closed = False
        super().__init__(cwd=self.workspace, timeout=timeout, env={}, persist_env=False)
        # A login shell would source the local user's profile; Sidecar runs a
        # plain non-login bash -c on the daemon side, so skip the snapshot.
        self._snapshot_ready = False
        self._prefer_nonlogin = True

    def get_temp_dir(self) -> str:
        return str(self._settings.get("temp_dir") or "/tmp")

    def _normalize_cwd(self, cwd: str | None) -> str:
        """Keep every command inside the daemon's local workspace.

        The remote tool layer can plan with a host path (``/Users/...``) or the
        remote home (``~``) that is meaningless on the local machine. The daemon
        resolves the workspace; commands are anchored there unless the caller
        names a path inside it.
        """
        workspace = str(self.workspace or "").strip()
        requested = str(cwd or "").strip()
        if not workspace or workspace.startswith("~"):
            return requested or workspace
        if not requested or requested.startswith("~"):
            return workspace
        path = Path(requested)
        if not path.is_absolute():
            return str(Path(workspace) / path)
        try:
            path.resolve().relative_to(Path(workspace).resolve())
            return str(path)
        except (ValueError, OSError):
            return workspace

    def execute(self, command: str, cwd: str = "", **kwargs: Any):
        return super().execute(command, cwd=self._normalize_cwd(cwd), **kwargs)

    def _wrap_command(self, command: str, cwd: str) -> str:
        """Keep the model's original command visible to the daemon's policy.

        ``BaseEnvironment`` wraps the command in a shell script whose ``eval '…'``
        hides the command from simple pattern rules. The daemon receives the
        original as a base64 comment, classifies that, and executes the wrapper.
        """
        wrapped = super()._wrap_command(command, cwd)
        try:
            encoded = base64.b64encode(command.encode("utf-8")).decode("ascii")
        except Exception:
            return wrapped
        return f"# sidecar-policy-command: {encoded}\n{wrapped}"

    def _run_bash(
        self,
        cmd_string: str,
        *,
        login: bool = False,
        timeout: int = 120,
        stdin_data: str | None = None,
    ) -> _RemoteProcessHandle:
        def _exec() -> tuple[str, int]:
            result = self.client.execute(
                cmd_string,
                cwd=self.workspace,
                timeout=int(timeout),
                stdin=stdin_data,
            )
            return str(result.get("output") or ""), int(result.get("returncode") if result.get("returncode") is not None else 125)

        return _RemoteProcessHandle(_exec)

    def cleanup(self) -> None:
        self._closed = True


class SidecarProvider(TerminalEnvironmentProvider):  # type: ignore[misc,valid-type]
    """Register Sidecar as ``terminal.backend: sidecar``."""

    name = "sidecar"
    display_name = "Sidecar (local machine)"
    is_remote = True
    is_container = False
    skip_container_guards = False
    cache_path_base = None
    supports_streams = False

    def __init__(self, *, settings: Callable[[], Mapping[str, Any]] | None = None):
        self._settings = settings or config_mod.load_settings

    @property
    def description(self) -> str:
        return (
            "Run terminal and file-tool commands on the user's local machine through a paired "
            "Sidecar daemon. The local person approves risky commands; every decision is audited."
        )

    @property
    def env_description(self) -> str:
        return "the user's local machine (via the paired Sidecar daemon)"

    @property
    def default_cwd(self) -> str | None:
        try:
            workspace = str(self._settings().get("workspace") or "~")
        except Exception:
            workspace = "~"
        # Do not expand ``~`` here: this process is the remote brain, so its home
        # is not the local home. The daemon resolves the path and reports the
        # absolute local workspace; create_environment() uses that.
        return workspace or None

    def _settings_dict(self) -> dict[str, Any]:
        try:
            value = self._settings()
            return dict(value) if isinstance(value, Mapping) else {}
        except Exception:
            return {}

    def is_available(self) -> bool:
        data = self._settings_dict()
        return bool(str(data.get("url") or "").strip() and str(data.get("token") or "").strip())

    def check_requirements(self, config: dict[str, Any]) -> bool:
        return self.is_available()

    def probe(self) -> tuple[str, str]:
        if not self.is_available():
            return ("needs_setup", "Set the Sidecar URL and pairing token (run `hermes sidecar pair` locally).")
        try:
            health = SidecarClient.from_settings(self._settings_dict()).health(timeout=2.0)
        except SidecarError as exc:
            return ("unavailable", str(exc))
        workspace = health.get("workspace") or self._settings_dict().get("workspace") or "~"
        return ("ready", f"Local daemon reachable · workspace {workspace}")

    def setup_instructions(self) -> list[str]:
        return [
            "On the local machine: hermes sidecar serve",
            "On the local machine: hermes sidecar pair (print the URL and token)",
            "On this remote Hermes: hermes config set terminal.backend sidecar",
            "Set plugins.entries.sidecar.settings.url and .token from the pairing output",
            "Run: hermes sidecar test",
        ]

    def doctor_checks(self) -> list[tuple[bool, str, str]]:
        data = self._settings_dict()
        return [
            (bool(data.get("url")), "Sidecar URL", str(data.get("url") or "(unset)")),
            (bool(data.get("token")), "Sidecar token", "(set)" if data.get("token") else "(unset)"),
            (self.probe()[0] == "ready", "Sidecar daemon", self.probe()[1]),
        ]

    def create_environment(
        self,
        *,
        cwd: str,
        timeout: int,
        task_id: str = "default",
        image: str | None = None,
        container_config: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> SidecarEnvironment:
        data = self._settings_dict()
        workspace = str(data.get("workspace") or "~")
        client = SidecarClient.from_settings(data)
        # The daemon owns the local filesystem. Ask it for the resolved absolute
        # workspace so a configured ``~`` (or a relative path) becomes a real
        # local directory before the wrapper's ``cd`` runs.
        try:
            health = client.health(timeout=2.5)
            local_workspace = str(health.get("workspace") or "").strip()
            if local_workspace:
                workspace = local_workspace
        except SidecarError:
            # Let the first command surface the connection error with the
            # actionable message from the client.
            pass
        return SidecarEnvironment(
            client=client,
            workspace=workspace,
            timeout=int(timeout or data.get("timeout") or 300),
            task_id=task_id,
            settings=data,
        )
