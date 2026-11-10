# SPDX-License-Identifier: AGPL-3.0-or-later
"""Over real HTTP: the bearer backend guards the endpoint itself."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastmcp import Client

from mindyard.auth import add_token
from mindyard.mcp import build_configured_server
from mindyard.settings import Settings
from tests.conftest import git_init, make_wiki


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def bearer_server(tmp_path: Path) -> Iterator[tuple[str, str]]:
    root = tmp_path / "vaults" / "notes"
    make_wiki(root)
    (root / "wiki.yaml").write_text("mindyard: 1\nlabel: Notes\n", encoding="utf-8")
    git_init(root)
    token = add_token(tmp_path / "tokens.yaml", "laptop")
    port = _free_port()
    settings = Settings.from_env(
        {
            "MINDYARD_DATA_ROOT": str(tmp_path),
            "MINDYARD_AUTH": "bearer",
            "MINDYARD_PORT": str(port),
            "MINDYARD_TELEMETRY": "0",
        }
    )
    app = build_configured_server(settings).http_app(path="/mcp")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp", token
    server.should_exit = True
    thread.join(timeout=5)


def test_request_without_or_with_a_wrong_token_is_rejected(
    bearer_server: tuple[str, str],
) -> None:
    url, token = bearer_server
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    headers = {"Accept": "application/json, text/event-stream"}
    assert httpx.post(url, json=body, headers=headers).status_code == 401
    wrong = {**headers, "Authorization": f"Bearer {token}x"}
    assert httpx.post(url, json=body, headers=wrong).status_code == 401


async def test_valid_token_reaches_the_tools(bearer_server: tuple[str, str]) -> None:
    url, token = bearer_server
    async with Client(url, auth=token) as client:
        result = await client.call_tool("list_wikis", {})
    assert result.structured_content == {
        "result": [{"id": "notes", "label": "Notes", "description": ""}]
    }


@pytest.mark.parametrize(
    ("path", "media_type"),
    [("/icon-96.png", "image/png"), ("/favicon.ico", "image/png"), ("/icon.svg", "image/svg+xml")],
)
def test_icons_are_public(bearer_server: tuple[str, str], path: str, media_type: str) -> None:
    url, _token = bearer_server
    response = httpx.get(url.removesuffix("/mcp") + path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(media_type)
