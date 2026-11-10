# SPDX-License-Identifier: AGPL-3.0-or-later
"""The request gate: identify, authorise, bind the tenant.

Runs on every MCP request (``on_request``), the handshake and tool listing
included. In order: the auth backend turns the verified token into an identity,
the access policy decides whether it may come in, the resolver picks its tenant,
and the tenant is bound to the request for the tools to read. Any refusal is the
same terse message: the client learns nothing about why, or what is behind.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

from mindyard.auth import AccessPolicy, AuthBackend
from mindyard.identity import Identity
from mindyard.tenancy import NoTenantError, TenantResolver, bound_tenant

ACCESS_DENIED = "Access denied: account not authorised for this server."

_identity: ContextVar[Identity | None] = ContextVar("mindyard_identity", default=None)


def current_identity() -> Identity | None:
    """The caller of the request being served (``None`` without auth)."""
    return _identity.get()


@contextmanager
def _bound_identity(identity: Identity | None) -> Iterator[None]:
    token = _identity.set(identity)
    try:
        yield
    finally:
        _identity.reset(token)


class TenantGateMiddleware(Middleware):
    def __init__(
        self, backend: AuthBackend, policy: AccessPolicy, resolver: TenantResolver
    ) -> None:
        self._backend = backend
        self._policy = policy
        self._resolver = resolver

    async def on_request(
        self, context: MiddlewareContext[Any], call_next: CallNext[Any, Any]
    ) -> Any:
        identity = self._backend.identity(get_access_token())
        if not self._policy.allows(identity):
            raise ToolError(ACCESS_DENIED)
        try:
            tenant = self._resolver.resolve(identity)
        except NoTenantError:
            raise ToolError(ACCESS_DENIED) from None
        with bound_tenant(tenant), _bound_identity(identity):
            return await call_next(context)
