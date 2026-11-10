# SPDX-License-Identifier: AGPL-3.0-or-later
"""A consent page whose CSRF token survives being loaded twice.

FastMCP's OAuth proxy issues a fresh CSRF token every time ``GET /consent`` is
served, and stores it on the transaction. Any second load of the same URL thus
invalidates the form the user is looking at. Second loads happen in practice:
some mobile browsers hand visited URLs to a scanning service, which fetches the
page within a second, so the user's "Approve" arrives with a stale token
("Invalid or expired consent token").

This mixin keeps the token stable for the lifetime of the transaction: when the
transaction already holds an unexpired token, a reload is served that same
token. The double-submit check is untouched. A third party learning the token
gains nothing: the token is only accepted together with the browser's own
``MCP_CONSENT_STATE`` cookie, which is ``SameSite=Lax`` and therefore never
attached to a cross-site POST.

It post-processes FastMCP's response instead of copying its private method, so
it depends on three internals only: the transaction store and its
``csrf_token``/``csrf_expires_at`` fields, the cookie helpers, and the token
appearing verbatim in the rendered form. ``tests/auth/test_consent.py`` replays
the race end to end and fails if any of them changes.
"""

from __future__ import annotations

import time
from typing import Any

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse

CONSENT_COOKIE = "MCP_CONSENT_STATE"


class StableConsentMixin:
    """Mix into an ``OAuthProxy`` subclass, before it in the bases."""

    async def _show_consent_page(self, request: Request) -> HTMLResponse | RedirectResponse:
        proxy: Any = self
        txn_id = request.query_params.get("txn_id")
        previous: tuple[str, float] | None = None
        if txn_id:
            txn = await proxy._transaction_store.get(key=txn_id)
            if txn is not None and txn.csrf_token and (txn.csrf_expires_at or 0) > time.time():
                previous = (txn.csrf_token, float(txn.csrf_expires_at))

        response: HTMLResponse | RedirectResponse = await super()._show_consent_page(  # type: ignore[misc]
            request
        )
        if previous is None or response.status_code != 200 or not txn_id:
            return response
        txn = await proxy._transaction_store.get(key=txn_id)
        fresh = txn.csrf_token if txn is not None else None
        body = bytes(response.body)
        if not fresh or fresh == previous[0] or fresh.encode() not in body:
            return response

        token, expires_at = previous
        txn.csrf_token, txn.csrf_expires_at = token, expires_at
        ttl = max(1, int(expires_at - time.time()))
        await proxy._transaction_store.put(key=txn_id, value=txn, ttl=ttl)

        response.body = body.replace(fresh.encode(), token.encode())
        response.headers["content-length"] = str(len(response.body))
        cookie_name = proxy._cookie_name(CONSENT_COOKIE)
        response.raw_headers = [
            (k, v)
            for k, v in response.raw_headers
            if not (k == b"set-cookie" and v.startswith(cookie_name.encode() + b"="))
        ]
        tokens = [t for t in proxy._decode_list_cookie(request, CONSENT_COOKIE) if t != token]
        proxy._set_list_cookie(
            response, CONSENT_COOKIE, proxy._encode_list_cookie([*tokens, token]), max_age=ttl
        )
        return response
