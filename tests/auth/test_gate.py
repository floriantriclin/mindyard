# SPDX-License-Identifier: AGPL-3.0-or-later
"""A denied account is refused at the OAuth callback, before it holds a token."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import fastmcp
import pytest
from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken
from fastmcp.server.auth.providers.google import GoogleProvider
from starlette.testclient import TestClient

from mindyard.auth.backends import GoogleAuth, StableConsentGoogleProvider
from mindyard.auth.gate import DENIED_DESCRIPTION
from mindyard.auth.policy import EmailAllowlist

BASE = "https://testserver"
REDIRECT = "http://localhost:9999/callback"
ALLOWED = "ada@example.org"
_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fastmcp.settings, "home", tmp_path / "state")


class _FakeGoogle:
    """Stands for the token endpoint: any code yields the same tokens."""

    async def fetch_token(self, **_: Any) -> dict[str, Any]:
        return {"access_token": "ya29.fake", "expires_in": 3600, "token_type": "Bearer"}

    async def aclose(self) -> None:
        return None


def _provider(email: str | None, gated: bool = True) -> GoogleProvider:
    if gated:
        auth = GoogleAuth(
            "id.apps.googleusercontent.com",
            "secret",
            BASE,
            policy=EmailAllowlist(frozenset({ALLOWED})),
        )
        provider = auth.provider()
        assert isinstance(provider, GoogleProvider)
    else:
        provider = StableConsentGoogleProvider(
            client_id="id.apps.googleusercontent.com",
            client_secret="secret",
            base_url=BASE,
            required_scopes=["openid"],
        )

    async def verify_token(token: str) -> AccessToken | None:
        if email is None:
            return None
        claims = {"sub": "1234", "email": email, "email_verified": True}
        return AccessToken(token=token, client_id="1234", scopes=["openid"], claims=claims)

    provider._create_upstream_oauth_client = _FakeGoogle  # type: ignore[assignment,method-assign]
    provider._token_validator.verify_token = verify_token  # type: ignore[method-assign]
    return provider


def _sign_in(provider: GoogleProvider) -> str:
    """Register, authorize, approve, then return from Google; the final redirect."""
    app = FastMCP("t", auth=provider).http_app(path="/mcp")
    with TestClient(app, base_url=BASE) as browser:
        reg = browser.post(
            "/register",
            json={
                "redirect_uris": [REDIRECT],
                "client_name": "test",
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        )
        assert reg.status_code == 201, reg.text
        consent = browser.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": reg.json()["client_id"],
                "redirect_uri": REDIRECT,
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
                "state": "s",
                "scope": "openid",
            },
            follow_redirects=False,
        ).headers["location"]
        token = _CSRF.search(browser.get(consent).text)
        assert token is not None
        txn_id = parse_qs(urlparse(consent).query)["txn_id"][0]
        approve = browser.post(
            "/consent",
            data={"txn_id": txn_id, "action": "approve", "csrf_token": token.group(1)},
            follow_redirects=False,
        )
        assert approve.status_code == 302, approve.text
        state = parse_qs(urlparse(approve.headers["location"]).query)["state"][0]
        back = browser.get(
            "/auth/callback", params={"code": "google-code", "state": state}, follow_redirects=False
        )
        assert back.status_code == 302, back.text
        return str(back.headers["location"])


def _query(location: str) -> dict[str, str]:
    assert location.startswith(REDIRECT)
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


async def _stored(provider: GoogleProvider, code: str) -> Any:
    store: Any = provider._code_store  # type: ignore[attr-defined]
    return await store.get(key=code)


async def test_an_allowed_account_gets_a_code() -> None:
    provider = _provider(ALLOWED)
    location = _sign_in(provider)
    query = _query(location)
    assert query["state"] == "s"
    assert await _stored(provider, query["code"]) is not None


async def test_a_denied_account_gets_access_denied_and_no_code() -> None:
    provider = _provider("eve@example.org")
    location = _sign_in(provider)
    query = _query(location)
    assert query == {
        "error": "access_denied",
        "error_description": DENIED_DESCRIPTION,
        "state": "s",
    }


async def test_a_failed_verification_is_a_refusal() -> None:
    location = _sign_in(_provider(None))
    assert _query(location)["error"] == "access_denied"


async def test_the_refused_code_is_deleted() -> None:
    provider = _provider("eve@example.org")
    issued: list[str] = []
    store: Any = provider._code_store  # type: ignore[attr-defined]
    put = store.put

    async def spy(*, key: str, **kwargs: Any) -> Any:
        issued.append(key)
        return await put(key=key, **kwargs)

    store.put = spy
    _sign_in(provider)
    assert len(issued) == 1
    assert await _stored(provider, issued[0]) is None


async def test_upstream_proxy_hands_a_code_to_anyone() -> None:
    """Guards the test itself: without the gate, a denied account gets a code.

    If this starts failing, FastMCP refuses at the callback itself and the
    mixin may be redundant.
    """
    location = _sign_in(_provider("eve@example.org", gated=False))
    assert "code" in _query(location)
