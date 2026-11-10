# SPDX-License-Identifier: AGPL-3.0-or-later
"""The caller, as every layer above the core sees it.

Auth backends produce an :class:`Identity`; access policies and tenant
resolvers consume it. It lives on its own so tenancy never imports auth.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Identity:
    """An authenticated principal.

    ``(issuer, subject)`` is the stable key. The email is informative: it can
    change hands, so it never decides which tenant a caller lands in.
    """

    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool = False
    claims: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def key(self) -> tuple[str, str]:
        return (self.issuer, self.subject)


_UNSAFE = re.compile(r"[<>\r\n\x00]")


def git_author(identity: Identity | None) -> str | None:
    """``Name <email>`` for a commit authored by this caller, or ``None``.

    Only a verified email is used: an unverified one would let a caller sign
    commits as someone else. Without one, the commit falls back to the
    repository's own identity.
    """
    if identity is None or not identity.email or not identity.email_verified:
        return None
    name = identity.claims.get("name")
    if not isinstance(name, str) or not name.strip():
        name = identity.email.split("@", 1)[0]
    name = _UNSAFE.sub("", name).strip() or "mindyard user"
    email = _UNSAFE.sub("", identity.email).strip()
    return f"{name} <{email}>"
