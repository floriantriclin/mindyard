# SPDX-License-Identifier: AGPL-3.0-or-later
"""Settings refuse every combination that would expose the vaults."""

from __future__ import annotations

import pytest

from mindyard.settings import Settings, SettingsError

BASE = {"MINDYARD_DATA_ROOT": "/data"}
GOOGLE = {
    **BASE,
    "MINDYARD_AUTH": "google",
    "MINDYARD_GOOGLE_CLIENT_ID": "id",
    "MINDYARD_GOOGLE_CLIENT_SECRET": "secret",
    "MINDYARD_BASE_URL": "https://wiki.example.org/",
}


def test_defaults_are_local_and_unauthenticated() -> None:
    s = Settings.from_env(BASE)
    assert (s.auth, s.tenancy, s.host, s.port, s.path) == (
        "none",
        "single",
        "127.0.0.1",
        8787,
        "/mcp",
    )
    assert str(s.vaults_dir) == "/data/vaults"


@pytest.mark.parametrize(
    ("env", "fragment"),
    [
        ({}, "MINDYARD_DATA_ROOT"),
        ({**BASE, "MINDYARD_HOST": "0.0.0.0"}, "loopback"),
        ({**BASE, "MINDYARD_TENANCY": "mapped"}, "needs an auth backend"),
        ({**BASE, "MINDYARD_AUTH": "ldap"}, "expected one of"),
        ({**BASE, "MINDYARD_PORT": "http"}, "not a port"),
        ({**GOOGLE, "MINDYARD_GOOGLE_CLIENT_SECRET": ""}, "MINDYARD_GOOGLE_CLIENT_SECRET"),
        ({**GOOGLE, "MINDYARD_BASE_URL": " "}, "MINDYARD_BASE_URL"),
        (GOOGLE, "MINDYARD_ALLOWED_EMAILS"),
    ],
)
def test_unsafe_or_broken_combinations_are_refused(env: dict[str, str], fragment: str) -> None:
    with pytest.raises(SettingsError, match=fragment):
        Settings.from_env(env)


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_no_auth_on_loopback_is_allowed(host: str) -> None:
    assert Settings.from_env({**BASE, "MINDYARD_HOST": host}).host == host


def test_google_with_allowlist() -> None:
    s = Settings.from_env({**GOOGLE, "MINDYARD_ALLOWED_EMAILS": "A@example.org, b@example.org"})
    assert s.allowed_emails == frozenset({"a@example.org", "b@example.org"})
    assert s.base_url == "https://wiki.example.org"


def test_google_mapped_needs_no_allowlist() -> None:
    assert Settings.from_env({**GOOGLE, "MINDYARD_TENANCY": "mapped"}).tenancy == "mapped"


def test_bearer_may_listen_publicly() -> None:
    assert (
        Settings.from_env({**BASE, "MINDYARD_AUTH": "bearer", "MINDYARD_HOST": "0.0.0.0"}).auth
        == "bearer"
    )
