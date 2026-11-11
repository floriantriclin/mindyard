# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assemble a server from :class:`~mindyard.settings.Settings`.

Factories only: importing this module builds nothing and decides nothing, so a
hostile configuration is a call that fails, not an import that dies.
"""

from __future__ import annotations

import sys
from typing import Any, Literal

import fastmcp
from fastmcp import FastMCP

from mindyard.auth import (
    AccessPolicy,
    AllowAll,
    AllowAuthenticated,
    AuthBackend,
    BearerAuth,
    EmailAllowlist,
    GoogleAuth,
    NoAuth,
    TokenStore,
)
from mindyard.settings import Settings, SettingsError
from mindyard.tenancy import (
    SingleTenantResolver,
    TenantResolver,
    load_mapped_resolver,
    load_tenant,
)

from . import accesslog
from .server import build_server

UNAUTHENTICATED_WARNING = (
    "[mindyard] WARNING: no authentication (MINDYARD_AUTH=none). "
    "Loopback only; never expose this server."
)


def build_backend(settings: Settings) -> AuthBackend:
    if settings.auth == "bearer":
        return BearerAuth(TokenStore.load(settings.tokens_file))
    if settings.auth == "google":
        assert settings.google_client_id and settings.google_client_secret and settings.base_url
        return GoogleAuth(
            settings.google_client_id,
            settings.google_client_secret,
            settings.base_url,
            policy=build_policy(settings),
        )
    return NoAuth()


def build_policy(settings: Settings) -> AccessPolicy:
    """Who may come in, before any tenant is looked up.

    Bearer tokens and the absence of auth are explicit grants. With Google, any
    account on earth holds a valid token, so a single tenant requires an email
    allowlist (enforced by ``Settings.check``); in mapped mode the tenant table is
    the list, and an optional allowlist narrows it further.
    """
    if settings.auth == "google":
        if settings.allowed_emails:
            return EmailAllowlist(settings.allowed_emails)
        return AllowAuthenticated()
    return AllowAll()


def build_resolver(settings: Settings) -> TenantResolver:
    if settings.tenancy == "mapped":
        return load_mapped_resolver(settings.data_root)
    return SingleTenantResolver(load_tenant("default", settings.vaults_dir))


Transport = Literal["http", "stdio"]


def check_transport(settings: Settings, transport: Transport) -> None:
    """Over stdio the caller is the parent process, run by the vault's owner.

    There is no token to verify on a pipe, so only the unauthenticated, single
    tenant setup makes sense; anything else would pretend to a check it cannot do.
    """
    if transport == "stdio" and settings.auth != "none":
        raise SettingsError(
            f"--stdio with MINDYARD_AUTH={settings.auth}: a stdio server serves the local "
            "user who launched it and verifies no token. Unset MINDYARD_AUTH, or serve over HTTP."
        )


def build_configured_server(
    settings: Settings | None = None, transport: Transport = "http"
) -> FastMCP[Any]:
    settings = settings or Settings.from_env()
    check_transport(settings, transport)
    # The OAuth proxy keeps its state under FastMCP's home; keep it with the data.
    fastmcp.settings.home = settings.state_dir
    backend = build_backend(settings)
    if isinstance(backend, NoAuth) and transport == "http":
        print(UNAUTHENTICATED_WARNING, file=sys.stderr)
    return build_server(
        backend,
        build_policy(settings),
        build_resolver(settings),
        telemetry=settings.telemetry,
        website_url=settings.base_url,
    )


def run(settings: Settings | None = None, transport: Transport = "http") -> None:
    settings = settings or Settings.from_env()
    server = build_configured_server(settings, transport)
    if transport == "stdio":
        # stdout carries the protocol; telemetry already writes to stderr.
        server.run(transport="stdio", show_banner=False)
        return
    accesslog.install()
    server.run(
        transport="http",
        host=settings.host,
        port=settings.port,
        path=settings.path,
        show_banner=False,
    )
