# SPDX-License-Identifier: AGPL-3.0-or-later
"""Access policies: may this identity use the server at all.

Applied to every MCP request, the handshake included: the server instructions
and the tool list already describe the wikis, so an identity off the list must
not even learn what is behind the door.
"""

from __future__ import annotations

from typing import Protocol

from mindyard.identity import Identity


class AccessPolicy(Protocol):
    def allows(self, identity: Identity | None) -> bool: ...


class AllowAll:
    """For backends whose credentials are explicit grants (bearer, no auth)."""

    def allows(self, identity: Identity | None) -> bool:
        return True


class AllowAuthenticated:
    """Any verified identity; the tenant map then decides what it sees."""

    def allows(self, identity: Identity | None) -> bool:
        return identity is not None


class EmailAllowlist:
    """A verified email on the list. An empty list denies everyone."""

    def __init__(self, emails: frozenset[str]) -> None:
        self._emails = frozenset(e.strip().lower() for e in emails if e.strip())

    def allows(self, identity: Identity | None) -> bool:
        return (
            identity is not None
            and identity.email_verified
            and identity.email is not None
            and identity.email in self._emails
        )
