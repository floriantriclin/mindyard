# SPDX-License-Identifier: AGPL-3.0-or-later
"""Map an identity to its tenant.

The tenant is always derived from who is calling, never from an argument: no
tool takes a tenant parameter, so no prompt can name someone else's.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from mindyard.identity import Identity

from .tenant import Tenant, TenantConfigError, load_tenant

_TENANT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class NoTenantError(Exception):
    """The caller maps to no tenant. Deliberately uninformative to the client."""

    def __init__(self) -> None:
        super().__init__("Access denied: no workspace for this account.")


class TenantResolver(Protocol):
    def resolve(self, identity: Identity | None) -> Tenant: ...


class SingleTenantResolver:
    """Self-hosting: one tenant, served to whoever the access policy lets in."""

    def __init__(self, tenant: Tenant) -> None:
        self._tenant = tenant

    def resolve(self, identity: Identity | None) -> Tenant:
        return self._tenant


class MappedTenantResolver:
    """Several tenants; ``(issuer, subject)`` pairs map to exactly one each.

    An unauthenticated caller, or an identity absent from the map, resolves to
    nothing: the server fails closed. The refused identity is logged for the
    operator (to stderr, never to the client), since the subject is what the
    operator needs to add to ``tenants.yaml``.
    """

    def __init__(self, tenants: Mapping[str, Tenant], members: Mapping[tuple[str, str], str]):
        unknown = sorted(set(members.values()) - set(tenants))
        if unknown:
            raise TenantConfigError(f"members point to unknown tenants: {', '.join(unknown)}")
        self._tenants = dict(tenants)
        self._members = dict(members)

    def resolve(self, identity: Identity | None) -> Tenant:
        if identity is None:
            raise NoTenantError()
        tenant_id = self._members.get(identity.key)
        if tenant_id is None:
            print(
                f"[mindyard] no tenant for issuer={identity.issuer!r} subject={identity.subject!r}",
                file=sys.stderr,
            )
            raise NoTenantError()
        return self._tenants[tenant_id]


class _Member(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str
    subject: str


class _TenantEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    members: list[_Member]


class _TenantsFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tenants: dict[str, _TenantEntry]


def load_mapped_resolver(data_root: Path) -> MappedTenantResolver:
    """Build the resolver from ``<data_root>/tenants.yaml``.

    Each tenant's vaults live under ``<data_root>/tenants/<id>/``. A member may
    belong to one tenant only: an identity listed twice is a configuration
    error, not a choice left to dictionary order.
    """
    source = data_root / "tenants.yaml"
    try:
        parsed = _TenantsFile.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))
    except OSError as exc:
        raise TenantConfigError(f"{source}: cannot read ({exc.strerror})") from exc
    except (yaml.YAMLError, ValidationError) as exc:
        raise TenantConfigError(f"{source}: invalid ({exc})") from exc

    tenants: dict[str, Tenant] = {}
    members: dict[tuple[str, str], str] = {}
    for tenant_id, entry in parsed.tenants.items():
        if not _TENANT_ID_RE.match(tenant_id):
            raise TenantConfigError(f"{source}: invalid tenant id {tenant_id!r}")
        tenants[tenant_id] = load_tenant(tenant_id, data_root / "tenants" / tenant_id)
        for member in entry.members:
            key = (member.issuer, member.subject)
            if key in members:
                raise TenantConfigError(
                    f"{source}: subject {member.subject!r} of {member.issuer!r} "
                    f"is listed in both '{members[key]}' and '{tenant_id}'"
                )
            members[key] = tenant_id
    return MappedTenantResolver(tenants, members)
