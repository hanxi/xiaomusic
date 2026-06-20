import asyncio
import importlib
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import HTTPException

from xiaomusic.api.dependencies import _state
from xiaomusic.config import Config

_state.initialize(SimpleNamespace(config=Config(), log=SimpleNamespace()))

file_router = importlib.import_module("xiaomusic.api.routers.file")


def test_redact_url_for_log_hides_sensitive_query_values():
    url = "https://example.com/audio.mp3?token=abc&name=song&signature=secret"

    redacted = file_router._redact_url_for_log(url)

    assert "token=%2A%2A%2A" in redacted
    assert "signature=%2A%2A%2A" in redacted
    assert "name=song" in redacted
    assert "abc" not in redacted
    assert "secret" not in redacted


def test_validate_proxy_target_blocks_private_hosts_by_default(monkeypatch):
    monkeypatch.setattr(
        file_router,
        "config",
        SimpleNamespace(
            proxy_allow_private_hosts=False,
            get_self_netloc=lambda: "example.com:8090",
        ),
    )

    try:
        asyncio.run(file_router._validate_proxy_target(urlparse("http://127.0.0.1/a")))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("private proxy target should be blocked")


def test_validate_proxy_target_allows_configured_self_netloc(monkeypatch):
    monkeypatch.setattr(
        file_router,
        "config",
        SimpleNamespace(
            proxy_allow_private_hosts=False,
            get_self_netloc=lambda: "127.0.0.1:8090",
        ),
    )

    asyncio.run(file_router._validate_proxy_target(urlparse("http://127.0.0.1:8090/a")))
