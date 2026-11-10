# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tenant of the request being served.

Set by a middleware once per request, read by the tools. Reading it when it was
never set is an error, not a default: a code path that forgot the middleware
must fail closed rather than fall back to some tenant.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from .tenant import Tenant

_current: ContextVar[Tenant | None] = ContextVar("mindyard_tenant", default=None)


class TenantNotBoundError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("No tenant bound to this request.")


def current_tenant() -> Tenant:
    tenant = _current.get()
    if tenant is None:
        raise TenantNotBoundError()
    return tenant


@contextmanager
def bound_tenant(tenant: Tenant) -> Iterator[Tenant]:
    token = _current.set(tenant)
    try:
        yield tenant
    finally:
        _current.reset(token)
