# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tenants: a root directory and the wikis discovered under it."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mindyard.core.config import WikiSet
from mindyard.schema import Wiki, discover_wikis


class TenantConfigError(ValueError):
    """A tenant that cannot be served; the message is operator-facing."""


@dataclass(frozen=True)
class Tenant:
    id: str
    root: Path
    wikis: dict[str, Wiki] = field(default_factory=dict)

    def wiki_set(self) -> WikiSet:
        """The core's view: only this tenant's wikis, nothing else."""
        return WikiSet({wid: w.config for wid, w in self.wikis.items()})


def load_tenant(tenant_id: str, root: Path) -> Tenant:
    """Discover a tenant's wikis; any problem is fatal.

    Every wiki root must resolve inside the tenant root. A vault directory that
    is a symlink to somewhere else (another tenant's vault, for instance) would
    otherwise pass path confinement, which is checked per wiki root only.
    """
    tenant_root = root.resolve()
    wikis, problems = discover_wikis(root)
    for wiki_id, wiki in wikis.items():
        if not wiki.config.root.is_relative_to(tenant_root):
            problems.append(f"tenant '{tenant_id}': wiki '{wiki_id}' resolves outside {root}")
    if problems:
        raise TenantConfigError("\n".join(problems))
    return Tenant(id=tenant_id, root=tenant_root, wikis=wikis)
