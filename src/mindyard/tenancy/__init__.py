# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tenancy: which wikis a request may see, derived from the caller's identity."""

from .context import TenantNotBoundError, bound_tenant, current_tenant
from .resolver import (
    MappedTenantResolver,
    NoTenantError,
    SingleTenantResolver,
    TenantResolver,
    load_mapped_resolver,
)
from .tenant import Tenant, TenantConfigError, load_tenant

__all__ = [
    "MappedTenantResolver",
    "NoTenantError",
    "SingleTenantResolver",
    "Tenant",
    "TenantConfigError",
    "TenantNotBoundError",
    "TenantResolver",
    "bound_tenant",
    "current_tenant",
    "load_mapped_resolver",
    "load_tenant",
]
