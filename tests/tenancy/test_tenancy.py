# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tenant isolation: two tenants, the same wiki id, no crossing."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from mindyard.core import operations
from mindyard.core.errors import PathEscapeError, UnknownWikiError
from mindyard.core.operations import Operation
from mindyard.identity import Identity
from mindyard.tenancy import (
    NoTenantError,
    SingleTenantResolver,
    TenantConfigError,
    TenantNotBoundError,
    bound_tenant,
    current_tenant,
    load_mapped_resolver,
    load_tenant,
)
from tests.conftest import git_init, make_wiki

ISSUER = "https://issuer.example"
ALICE = Identity(ISSUER, "sub-alice", "alice@example.org", True)
BOB = Identity(ISSUER, "sub-bob", "bob@example.org", True)


def _vault(tenant_dir: Path, wiki_id: str, label: str) -> Path:
    root = tenant_dir / wiki_id
    make_wiki(root)
    (root / "wiki.yaml").write_text(f"mindyard: 1\nlabel: {label}\n", encoding="utf-8")
    (root / "wiki" / "owner.md").write_text(f"{label}\n", encoding="utf-8")
    git_init(root)
    return root


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    _vault(tmp_path / "tenants" / "alice", "notes", "Alice notes")
    _vault(tmp_path / "tenants" / "bob", "notes", "Bob notes")
    _vault(tmp_path / "tenants" / "bob", "garden", "Bob garden")
    (tmp_path / "tenants.yaml").write_text(
        f"""\
tenants:
  alice: {{members: [{{issuer: "{ISSUER}", subject: sub-alice}}]}}
  bob: {{members: [{{issuer: "{ISSUER}", subject: sub-bob}}]}}
""",
        encoding="utf-8",
    )
    return tmp_path


def test_same_wiki_id_resolves_to_each_tenant_own_vault(data_root: Path) -> None:
    resolver = load_mapped_resolver(data_root)
    for identity, expected in ((ALICE, "Alice notes\n"), (BOB, "Bob notes\n")):
        wikis = resolver.resolve(identity).wiki_set()
        view = operations.read_page(wikis.get_wiki("notes"), "wiki/owner.md")
        assert view["content"] == expected


def test_a_tenant_never_sees_another_tenant_wiki_ids(data_root: Path) -> None:
    resolver = load_mapped_resolver(data_root)
    alice = resolver.resolve(ALICE).wiki_set()
    assert sorted(alice) == ["notes"]
    with pytest.raises(UnknownWikiError) as info:
        alice.get_wiki("garden")
    assert "garden" not in str(info.value).split("Known wikis:")[1]


def test_relative_path_cannot_reach_a_sibling_tenant(data_root: Path) -> None:
    alice_notes = load_mapped_resolver(data_root).resolve(ALICE).wiki_set().get_wiki("notes")
    for path in ("../../bob/notes/wiki/owner.md", "../../../tenants/bob/notes/wiki/owner.md"):
        with pytest.raises(PathEscapeError):
            operations.read_page(alice_notes, path)
        with pytest.raises(PathEscapeError):
            operations.write_batch(
                alice_notes, [Operation(op="create", path=path, content="x")], "leak"
            )
    bob_page = data_root / "tenants" / "bob" / "notes" / "wiki" / "owner.md"
    assert bob_page.read_text(encoding="utf-8") == "Bob notes\n"


def test_writes_land_in_the_caller_tenant_only(data_root: Path) -> None:
    resolver = load_mapped_resolver(data_root)
    alice_notes = resolver.resolve(ALICE).wiki_set().get_wiki("notes")
    operations.write_batch(
        alice_notes, [Operation(op="create", path="wiki/new.md", content="a\n")], "add"
    )
    assert (data_root / "tenants" / "alice" / "notes" / "wiki" / "new.md").exists()
    assert not (data_root / "tenants" / "bob" / "notes" / "wiki" / "new.md").exists()


def test_unknown_or_missing_identity_is_refused(data_root: Path) -> None:
    resolver = load_mapped_resolver(data_root)
    with pytest.raises(NoTenantError):
        resolver.resolve(None)
    with pytest.raises(NoTenantError):
        resolver.resolve(Identity(ISSUER, "sub-mallory", "alice@example.org", True))
    # Same subject, other issuer: another principal entirely.
    with pytest.raises(NoTenantError):
        resolver.resolve(Identity("https://other.example", "sub-alice"))


def test_email_never_selects_a_tenant(data_root: Path) -> None:
    impostor = Identity(ISSUER, "sub-new", email="bob@example.org", email_verified=True)
    with pytest.raises(NoTenantError):
        load_mapped_resolver(data_root).resolve(impostor)


def test_identity_listed_in_two_tenants_is_a_config_error(data_root: Path) -> None:
    (data_root / "tenants.yaml").write_text(
        f"""\
tenants:
  alice: {{members: [{{issuer: "{ISSUER}", subject: sub-x}}]}}
  bob: {{members: [{{issuer: "{ISSUER}", subject: sub-x}}]}}
""",
        encoding="utf-8",
    )
    with pytest.raises(TenantConfigError, match="both"):
        load_mapped_resolver(data_root)


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_symlinked_vault_into_another_tenant_is_refused(data_root: Path) -> None:
    (data_root / "tenants" / "alice" / "stolen").symlink_to(data_root / "tenants" / "bob" / "notes")
    with pytest.raises(TenantConfigError, match="outside"):
        load_mapped_resolver(data_root)


def test_single_tenant_serves_everyone_the_access_policy_lets_in(tmp_path: Path) -> None:
    _vault(tmp_path / "vaults", "notes", "Mine")
    tenant = load_tenant("default", tmp_path / "vaults")
    resolver = SingleTenantResolver(tenant)
    assert resolver.resolve(None) is tenant
    assert resolver.resolve(ALICE) is tenant


def test_broken_vault_fails_tenant_loading(tmp_path: Path) -> None:
    _vault(tmp_path / "vaults", "notes", "Mine")
    (tmp_path / "vaults" / "notes" / "wiki.yaml").write_text("mindyard: 1\n", encoding="utf-8")
    with pytest.raises(TenantConfigError, match="label"):
        load_tenant("default", tmp_path / "vaults")


def test_current_tenant_fails_closed_when_unbound(tmp_path: Path) -> None:
    with pytest.raises(TenantNotBoundError):
        current_tenant()
    _vault(tmp_path / "vaults", "notes", "Mine")
    tenant = load_tenant("default", tmp_path / "vaults")
    with bound_tenant(tenant):
        assert current_tenant() is tenant
    with pytest.raises(TenantNotBoundError):
        current_tenant()
