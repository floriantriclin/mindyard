# SPDX-License-Identifier: AGPL-3.0-or-later
"""Refuse an identity at the OAuth callback, not only at the first MCP request.

FastMCP's OAuth proxy hands an authorization code to any account the upstream
provider signs in. With Google that is any account on earth: the access policy
then refuses every MCP request, but the client already holds a token. Claude.ai
keeps such a token and the connector stays stuck until it is disconnected.

This mixin checks the identity as soon as Google's tokens are in hand. A refused
identity gets no code: its code is deleted and the client is redirected with
``error=access_denied`` (RFC 6749, section 4.1.2.1), so it never stores a token.
The per-request gate stays the authority; this is the early, friendly refusal.

Like the consent mixin, it post-processes FastMCP's response instead of copying
its handler. It depends on the code store, the ``idp_tokens`` of a stored code
and the upstream token verifier; ``tests/auth/test_gate.py`` drives the whole
callback and fails if any of them changes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from fastmcp.server.auth import AccessToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

Admit = Callable[[AccessToken | None], bool]

DENIED_DESCRIPTION = "This account is not allowed on this server."


class CallbackGateMixin:
    """Mix into an ``OAuthProxy`` subclass, before it in the bases."""

    def __init__(self, *args: Any, admit: Admit, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._admit = admit

    async def _handle_idp_callback(self, request: Request) -> HTMLResponse | RedirectResponse:
        proxy: Any = self
        parent: Callable[[Request], Awaitable[HTMLResponse | RedirectResponse]]
        parent = super()._handle_idp_callback  # type: ignore[misc]
        response = await parent(request)
        if not isinstance(response, RedirectResponse):
            return response
        target = urlparse(response.headers["location"])
        params = parse_qs(target.query)
        code = params.get("code", [None])[0]
        if not code:
            return response
        stored = await proxy._code_store.get(key=code)
        if stored is not None and self._admit(await self._verify(stored.idp_tokens)):
            return response

        await proxy._code_store.delete(key=code)
        denied = {"error": "access_denied", "error_description": DENIED_DESCRIPTION}
        if "state" in params:
            denied["state"] = params["state"][0]
        kept = [(k, v) for k, vs in params.items() if k not in ("code", "state") for v in vs]
        location = target._replace(query=urlencode([*kept, *denied.items()])).geturl()
        refused = RedirectResponse(url=location, status_code=302)
        refused.raw_headers += [(k, v) for k, v in response.raw_headers if k == b"set-cookie"]
        return refused

    async def _verify(self, idp_tokens: dict[str, Any]) -> AccessToken | None:
        """The upstream verifier's verdict on the fresh tokens; failure denies."""
        proxy: Any = self
        access_token = idp_tokens.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            return None
        try:
            verified: AccessToken | None = await proxy._token_validator.verify_token(access_token)
        except Exception:
            return None
        return verified
