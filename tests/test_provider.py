from __future__ import annotations

import threading

import pytest

pytest.importorskip("tools.environments.base")
pytest.importorskip("agent.terminal_env_provider")

from sidecar import daemon  # noqa: E402
from sidecar.client import SidecarClient  # noqa: E402
from sidecar.provider import SidecarEnvironment, SidecarProvider  # noqa: E402


def start_server(tmp_path):
    server = daemon.create_server(
        host="127.0.0.1",
        port=0,
        token="provider-token",
        settings={"approval": "allow", "workspace": str(tmp_path), "timeout": 5, "audit": True},
        workspace=tmp_path,
        data_dir=tmp_path / ".data",
    )
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_base_environment_round_trip(tmp_path):
    server, thread, url = start_server(tmp_path)
    try:
        env = SidecarEnvironment(
            client=SidecarClient(url, "provider-token", workspace=str(tmp_path)),
            workspace=str(tmp_path),
            timeout=5,
        )
        result = env.execute("printf 'hello from BaseEnvironment\\n'")
        assert result["returncode"] == 0
        assert "hello from BaseEnvironment" in result["output"]
        assert env.execute("pwd")["output"].strip() == str(tmp_path)
        pipeline = env.execute("printf 'x' | cat")
        assert pipeline["returncode"] == 0
        if getattr(env, "_pipe_marker", ""):
            assert pipeline["pipeline_status"] == [0, 0]
        assert env.execute("sh -c 'exit 7'")["returncode"] == 7
        denied = env.execute("sudo -n true")
        assert denied["returncode"] != 0
        assert "denied" in denied["output"].lower() or "privilege" in denied["output"].lower()
        # A remote host path that is meaningless locally is anchored to the
        # daemon's workspace instead of producing a 403.
        outside = env.execute("pwd", cwd="/tmp")
        assert outside["output"].strip() == str(tmp_path)
        env.cleanup()
    finally:
        stop(server, thread)


def test_configured_tilde_resolves_on_the_local_daemon(tmp_path):
    server, thread, url = start_server(tmp_path)
    try:
        settings = {"url": url, "token": "provider-token", "workspace": "~", "timeout": 5}
        provider = SidecarProvider(settings=lambda: settings)
        env = provider.create_environment(cwd="~", timeout=5, task_id="test")
        result = env.execute("pwd")
        assert result["returncode"] == 0
        assert result["output"].strip() == str(tmp_path)
        env.cleanup()
    finally:
        stop(server, thread)


def test_provider_probe_and_config(tmp_path):
    server, thread, url = start_server(tmp_path)
    try:
        settings = {"url": url, "token": "provider-token", "workspace": str(tmp_path), "timeout": 5}
        provider = SidecarProvider(settings=lambda: settings)
        assert provider.is_available() is True
        status, detail = provider.probe()
        assert status == "ready", detail
        env = provider.create_environment(cwd=str(tmp_path), timeout=5, task_id="test")
        result = env.execute("printf ok")
        assert result["returncode"] == 0
        assert result["output"] == "ok"
        env.cleanup()
    finally:
        stop(server, thread)
