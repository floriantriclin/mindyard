# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authentication backends: who is calling.

A backend has two jobs. It supplies the FastMCP auth provider that guards the
HTTP endpoint (or none), and it turns the verified access token into a neutral
:class:`~mindyard.identity.Identity`. Deciding whether that identity may come in is
the access policy's job, and which wikis it sees is the tenant resolver's.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from fastmcp.server.auth import AccessToken, AuthProvider
from fastmcp.server.auth.providers.google import GoogleProvider

from mindyard.identity import Identity

from .consent import StableConsentMixin
from .gate import CallbackGateMixin
from .policy import AccessPolicy
from .tokens import BEARER_ISSUER, HashedTokenVerifier, TokenStore

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_SCOPES = ("openid", "email", "profile")


class AuthBackend(Protocol):
    name: str

    def provider(self) -> AuthProvider | None: ...

    def identity(self, token: AccessToken | None) -> Identity | None: ...


class NoAuth:
    """Local development only. The server refuses to listen beyond loopback."""

    name = "none"

    def provider(self) -> AuthProvider | None:
        return None

    def identity(self, token: AccessToken | None) -> Identity | None:
        return None


class BearerAuth:
    """Static bearer tokens, stored hashed; one named principal per token.

    Suited to Claude Code, Claude Desktop (through a stdio bridge) and scripts.
    Claude.ai custom connectors accept static headers only for some accounts,
    so OAuth remains the route there.
    """

    name = "bearer"

    def __init__(self, store: TokenStore) -> None:
        self._verifier = HashedTokenVerifier(store)

    def provider(self) -> AuthProvider | None:
        return self._verifier

    def identity(self, token: AccessToken | None) -> Identity | None:
        if token is None:
            return None
        return Identity(issuer=BEARER_ISSUER, subject=token.client_id)


def _attested(flag: Any) -> bool:
    """True only for an explicit affirmative flag, boolean or string.

    Google's tokeninfo returns ``"true"``/``"false"`` strings and userinfo a JSON
    boolean. ``"false"`` is a truthy Python string: a plain truth test would read
    a refusal as a proof.
    """
    if isinstance(flag, bool):
        return flag
    if isinstance(flag, str):
        return flag.strip().lower() == "true"
    return False


def email_verified(claims: Mapping[str, Any]) -> bool:
    """True only if every source present explicitly attests the email.

    The flag has two homes: ``email_verified`` at the top level and
    ``verified_email`` in the ``google_user_data`` profile, which is ``None``
    when the userinfo fetch fails. No flag is not a verification, and any source
    that disagrees is a refusal.
    """
    flags = [
        source[key]
        for source in (claims, claims.get("google_user_data"))
        if isinstance(source, Mapping)
        for key in ("email_verified", "verified_email")
        if key in source
    ]
    return bool(flags) and all(_attested(flag) for flag in flags)


def google_identity(claims: Mapping[str, Any] | None) -> Identity | None:
    """Identity from Google claims, or ``None`` without a subject."""
    if not claims:
        return None
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        return None
    email = claims.get("email")
    return Identity(
        issuer=GOOGLE_ISSUER,
        subject=subject,
        email=email.strip().lower() if isinstance(email, str) and email.strip() else None,
        email_verified=email_verified(claims),
        claims=dict(claims),
    )


class StableConsentGoogleProvider(StableConsentMixin, GoogleProvider):
    """Google OAuth proxy whose consent page tolerates a second load."""


class GatedGoogleProvider(CallbackGateMixin, StableConsentGoogleProvider):
    """The same proxy, refusing an identity the policy denies at the callback."""


class GoogleAuth:
    """OAuth through Google, proxied by FastMCP so Claude.ai can connect.

    The proxy persists client registrations and tokens under FastMCP's home
    directory: losing it forces every client to sign in again. Given the access
    policy, it also refuses a denied account at the callback, before the client
    holds a token.
    """

    name = "google"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str,
        redirect_path: str = "/auth/callback",
        policy: AccessPolicy | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url
        self._redirect_path = redirect_path
        self._policy = policy

    def provider(self) -> AuthProvider | None:
        options: dict[str, Any] = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "base_url": self._base_url,
            "redirect_path": self._redirect_path,
            "required_scopes": list(GOOGLE_SCOPES),
        }
        policy = self._policy
        if policy is None:
            return StableConsentGoogleProvider(**options)
        return GatedGoogleProvider(
            admit=lambda token: policy.allows(self.identity(token)), **options
        )

    def identity(self, token: AccessToken | None) -> Identity | None:
        return google_identity(token.claims if token is not None else None)
