# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assembly from settings: the right backend, policy and state directory."""

from __future__ import annotations

from pathlib import Path

import fastmcp
import pytest
from fastmcp.server.auth.providers.google import GoogleProvider

from mindyard.auth import AllowAll, AllowAuthenticated, EmailAllowlist
from mindyard.mcp import build_configured_server
from mindyard.mcp.app import build_policy
from mindyard.settings import Settings
from mindyard.tenancy import TenantConfigError
from tests.conftest import git_init, make_wiki


def _data_root(tmp_path: Path) -> Path:
    root = tmp_path / "vaults" / "notes"
    make_wiki(root)
    (root / "wiki.yaml").write_text("mindyard: 1\nlabel: Notes\n", encoding="utf-8")
    git_init(root)
    return tmp_path


def _google(tmp_path: Path, **extra: str) -> Settings:
    return Settings.from_env(
        {
            "MINDYARD_DATA_ROOT": str(tmp_path),
            "MINDYARD_AUTH": "google",
            "MINDYARD_GOOGLE_CLIENT_ID": "id.apps.googleusercontent.com",
            "MINDYARD_GOOGLE_CLIENT_SECRET": "secret",
            "MINDYARD_BASE_URL": "https://wiki.example.org",
            **extra,
        }
    )


def test_google_server_keeps_oauth_state_under_the_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fastmcp.settings, "home", fastmcp.settings.home)
    settings = _google(_data_root(tmp_path), MINDYARD_ALLOWED_EMAILS="reader@example.org")
    server = build_configured_server(settings)
    assert isinstance(server.auth, GoogleProvider)
    assert fastmcp.settings.home == tmp_path / "state"


def test_policies_by_backend(tmp_path: Path) -> None:
    base = {"MINDYARD_DATA_ROOT": str(tmp_path)}
    assert isinstance(build_policy(Settings.from_env(base)), AllowAll)
    assert isinstance(
        build_policy(Settings.from_env({**base, "MINDYARD_AUTH": "bearer"})), AllowAll
    )
    single = _google(tmp_path, MINDYARD_ALLOWED_EMAILS="reader@example.org")
    assert isinstance(build_policy(single), EmailAllowlist)
    assert isinstance(
        build_policy(_google(tmp_path, MINDYARD_TENANCY="mapped")), AllowAuthenticated
    )


def test_broken_vault_stops_the_build(tmp_path: Path) -> None:
    root = _data_root(tmp_path)
    (root / "vaults" / "notes" / "wiki.yaml").write_text("mindyard: 1\n", encoding="utf-8")
    with pytest.raises(TenantConfigError, match="label"):
        build_configured_server(Settings.from_env({"MINDYARD_DATA_ROOT": str(root)}))
