# SPDX-License-Identifier: AGPL-3.0-or-later
"""The consent page survives a second load (a scanner fetching the same URL)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import fastmcp
import pytest
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from starlette.testclient import TestClient

from mindyard.auth.backends import StableConsentGoogleProvider

BASE = "https://testserver"
REDIRECT = "http://localhost:9999/callback"
_CSRF = re.compile(r'name="csrf_token" value="([^"]+)"')


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fastmcp.settings, "home", tmp_path / "state")


def _clients(provider_cls: type[GoogleProvider]) -> Iterator[tuple[TestClient, TestClient]]:
    provider = provider_cls(
        client_id="id.apps.googleusercontent.com",
        client_secret="secret",
        base_url=BASE,
        required_scopes=["openid"],
        jwt_signing_key="test-signing-key-" + "x" * 32,
    )
    app = FastMCP("t", auth=provider).http_app(path="/mcp")
    with TestClient(app, base_url=BASE) as browser, TestClient(app, base_url=BASE) as scanner:
        yield browser, scanner


def _consent_url(browser: TestClient) -> str:
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
    auth = browser.get(
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
    )
    assert auth.status_code == 302, auth.text
    location = auth.headers["location"]
    assert "/consent" in location
    return location


def _race(browser: TestClient, scanner: TestClient) -> int:
    """Browser loads the form, a scanner loads it again, browser approves."""
    url = _consent_url(browser)
    page = browser.get(url)
    token = _CSRF.search(page.text)
    assert token is not None
    scanner.get(url)
    txn_id = parse_qs(urlparse(url).query)["txn_id"][0]
    approve = browser.post(
        "/consent",
        data={"txn_id": txn_id, "action": "approve", "csrf_token": token.group(1)},
        follow_redirects=False,
    )
    if approve.status_code == 302:
        assert approve.headers["location"].startswith("https://accounts.google.com/")
    return approve.status_code


def test_approval_survives_a_second_load() -> None:
    for browser, scanner in _clients(StableConsentGoogleProvider):
        assert _race(browser, scanner) == 302


def test_upstream_provider_still_has_the_race() -> None:
    """Guards the test itself: without the mixin, the same sequence fails.

    If this starts passing, FastMCP fixed the race upstream and the mixin can go.
    """
    for browser, scanner in _clients(GoogleProvider):
        assert _race(browser, scanner) == 400


def test_a_forged_post_without_the_cookie_is_still_refused() -> None:
    for browser, scanner in _clients(StableConsentGoogleProvider):
        url = _consent_url(browser)
        token = _CSRF.search(browser.get(url).text)
        assert token is not None
        scanner.get(url)  # the scanner now holds the same token, but not the cookie
        txn_id = parse_qs(urlparse(url).query)["txn_id"][0]
        scanner.cookies.clear()
        forged = scanner.post(
            "/consent",
            data={"txn_id": txn_id, "action": "approve", "csrf_token": token.group(1)},
            follow_redirects=False,
        )
        assert forged.status_code == 403
