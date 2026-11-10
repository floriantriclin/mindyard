# SPDX-License-Identifier: AGPL-3.0-or-later
"""Static bearer tokens, stored as SHA-256 digests in ``tokens.yaml``.

Tokens are 256-bit random strings, so a fast hash is enough: there is nothing
to brute-force, and the file never holds a usable secret. Lookup is by digest,
so comparing a guess costs the same whatever it matches.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

import yaml
from fastmcp.server.auth import AccessToken, TokenVerifier
from pydantic import BaseModel, ConfigDict, Field, ValidationError

BEARER_ISSUER = "mindyard:bearer"
TOKEN_PREFIX = "myd_"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,62}$")


class TokenStoreError(ValueError):
    pass


def digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tokens: list[_Entry] = []


@dataclass(frozen=True)
class TokenStore:
    """Token digest to principal name. Loaded once, at startup."""

    by_digest: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> TokenStore:
        if not path.is_file():
            return cls({})
        try:
            parsed = _File.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        except (yaml.YAMLError, ValidationError) as exc:
            raise TokenStoreError(f"{path}: invalid ({exc})") from exc
        by_digest: dict[str, str] = {}
        for entry in parsed.tokens:
            if entry.sha256 in by_digest:
                raise TokenStoreError(f"{path}: duplicate token digest")
            by_digest[entry.sha256] = entry.name
        return cls(by_digest)


def add_token(path: Path, name: str) -> str:
    """Mint a token for ``name``, store its digest, return the clear token once."""
    if not _NAME_RE.match(name):
        raise TokenStoreError(f"invalid token name {name!r}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    entries = list((data or {}).get("tokens", []))
    if any(e.get("name") == name for e in entries):
        raise TokenStoreError(f"a token named {name!r} already exists")
    token = new_token()
    entries.append({"name": name, "sha256": digest(token)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"tokens": entries}, sort_keys=False), encoding="utf-8")
    path.chmod(0o600)
    return token


class HashedTokenVerifier(TokenVerifier):
    def __init__(self, store: TokenStore) -> None:
        super().__init__()
        self._store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        name = self._store.by_digest.get(digest(token))
        if name is None:
            return None
        return AccessToken(token=token, client_id=name, scopes=[], claims={"sub": name})
