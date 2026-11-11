from __future__ import annotations

import pytest

from sidecar.client import SidecarClient, SidecarError


def test_missing_token_is_actionable():
    client = SidecarClient("http://127.0.0.1:9", "", workspace="/tmp")
    with pytest.raises(SidecarError) as exc:
        client.health(timeout=0.2)
    assert "not paired" in str(exc.value)


def test_bad_url_is_rejected():
    with pytest.raises(SidecarError) as exc:
        SidecarClient("ftp://example.com", "x")
    assert "http://" in str(exc.value)


def test_unreachable_daemon_is_actionable():
    client = SidecarClient("http://127.0.0.1:1", "x", workspace="/tmp")
    with pytest.raises(SidecarError) as exc:
        client.health(timeout=0.2)
    assert "hermes sidecar serve" in str(exc.value)
