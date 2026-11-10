# SPDX-License-Identifier: AGPL-3.0-or-later
"""Auth backends, bearer tokens and access policies."""

from __future__ import annotations

import stat
from pathlib import Path
from typing import Any

import pytest

from mindyard.auth import (
    AllowAll,
    AllowAuthenticated,
    BearerAuth,
    EmailAllowlist,
    NoAuth,
    TokenStore,
    TokenStoreError,
    add_token,
    google_identity,
)
from mindyard.auth.backends import GOOGLE_ISSUER, email_verified
from mindyard.auth.tokens import BEARER_ISSUER, digest
from mindyard.identity import Identity

EMAIL = "reader@example.org"


def _google(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "sub": "1234",
        "email": EMAIL,
        "email_verified": "true",
        "google_user_data": {"verified_email": True},
    }
    claims.update(overrides)
    return claims


# --- Google identity --------------------------------------------------------


def test_google_identity_keys_on_subject_and_normalises_email() -> None:
    identity = google_identity(_google(email="Reader@Example.ORG"))
    assert identity is not None
    assert identity.key == (GOOGLE_ISSUER, "1234")
    assert identity.email == EMAIL
    assert identity.email_verified is True


@pytest.mark.parametrize("claims", [None, {}, _google(sub=None), _google(sub="")])
def test_google_identity_without_subject_is_none(claims: dict[str, Any] | None) -> None:
    assert google_identity(claims) is None


@pytest.mark.parametrize(
    ("claims", "verified"),
    [
        (_google(), True),
        (_google(email_verified=True, google_user_data=None), True),
        (_google(email_verified="false"), False),  # truthy string, still a refusal
        (_google(google_user_data={"verified_email": False}), False),  # contradiction
        ({"sub": "1", "email": EMAIL}, False),  # no flag at all
        (_google(email_verified="yes"), False),  # not an explicit "true"
    ],
)
def test_email_verified_requires_explicit_agreeing_attestations(
    claims: dict[str, Any], verified: bool
) -> None:
    assert email_verified(claims) is verified


# --- Policies ---------------------------------------------------------------


def test_email_allowlist() -> None:
    policy = EmailAllowlist(frozenset({" Reader@Example.org "}))
    assert policy.allows(Identity(GOOGLE_ISSUER, "1", EMAIL, True))
    assert not policy.allows(Identity(GOOGLE_ISSUER, "1", EMAIL, False))
    assert not policy.allows(Identity(GOOGLE_ISSUER, "1", "other@example.org", True))
    assert not policy.allows(Identity(GOOGLE_ISSUER, "1", None, True))
    assert not policy.allows(None)
    assert not EmailAllowlist(frozenset()).allows(Identity(GOOGLE_ISSUER, "1", EMAIL, True))


def test_allow_authenticated_and_allow_all() -> None:
    someone = Identity("i", "s")
    assert AllowAuthenticated().allows(someone)
    assert not AllowAuthenticated().allows(None)
    assert AllowAll().allows(None)


def test_no_auth_has_no_provider_and_no_identity() -> None:
    assert NoAuth().provider() is None
    assert NoAuth().identity(None) is None


# --- Bearer tokens ----------------------------------------------------------


def test_add_token_stores_only_a_private_digest(tmp_path: Path) -> None:
    path = tmp_path / "tokens.yaml"
    token = add_token(path, "laptop")
    content = path.read_text(encoding="utf-8")
    assert token.startswith("myd_") and len(token) > 40
    assert token not in content
    assert digest(token) in content
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert TokenStore.load(path).by_digest == {digest(token): "laptop"}


def test_add_token_refuses_duplicates_and_bad_names(tmp_path: Path) -> None:
    path = tmp_path / "tokens.yaml"
    add_token(path, "laptop")
    with pytest.raises(TokenStoreError, match="already exists"):
        add_token(path, "laptop")
    with pytest.raises(TokenStoreError, match="invalid"):
        add_token(path, "Bad Name")


def test_token_store_rejects_malformed_file(tmp_path: Path) -> None:
    path = tmp_path / "tokens.yaml"
    path.write_text("tokens: [{name: x, sha256: nothex}]\n", encoding="utf-8")
    with pytest.raises(TokenStoreError):
        TokenStore.load(path)


def test_missing_token_file_is_an_empty_store(tmp_path: Path) -> None:
    assert TokenStore.load(tmp_path / "absent.yaml").by_digest == {}


async def test_bearer_backend_verifies_and_names_the_principal(tmp_path: Path) -> None:
    path = tmp_path / "tokens.yaml"
    token = add_token(path, "laptop")
    backend = BearerAuth(TokenStore.load(path))
    verifier = backend.provider()
    assert verifier is not None
    access = await verifier.verify_token(token)
    assert access is not None
    assert backend.identity(access) == Identity(BEARER_ISSUER, "laptop")
    assert await verifier.verify_token(token + "x") is None
    assert await verifier.verify_token("") is None
    assert backend.identity(None) is None
