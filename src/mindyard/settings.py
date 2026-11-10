# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server settings, read from ``MINDYARD_*`` environment variables.

Settings are checked as a whole when the server is built. A combination that
would expose the vaults is refused with a message naming what to fix, rather
than degraded into something that runs: an open server on a public interface,
OAuth with one variable forgotten, Google sign-in with no allowlist.

Layout under ``MINDYARD_DATA_ROOT``:

- ``vaults/<wiki>/``: the vaults, in single-tenant mode;
- ``tenants.yaml`` and ``tenants/<tenant>/<wiki>/``: in mapped mode;
- ``tokens.yaml``: bearer token digests;
- ``state/``: OAuth proxy state (client registrations, tokens). Not a cache:
  deleting it signs every client out.
"""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Tenancy = Literal["single", "mapped"]
AuthName = Literal["none", "bearer", "google"]

_GOOGLE_VARS = ("MINDYARD_GOOGLE_CLIENT_ID", "MINDYARD_GOOGLE_CLIENT_SECRET", "MINDYARD_BASE_URL")


class SettingsError(ValueError):
    pass


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _choice[T: str](env: Mapping[str, str], name: str, default: str, allowed: tuple[T, ...]) -> T:
    value = (env.get(name) or default).strip().lower()
    for option in allowed:
        if value == option:
            return option
    raise SettingsError(f"{name}={value!r}: expected one of {', '.join(allowed)}")


@dataclass(frozen=True)
class Settings:
    data_root: Path
    tenancy: Tenancy = "single"
    auth: AuthName = "none"
    host: str = "127.0.0.1"
    port: int = 8787
    path: str = "/mcp"
    base_url: str | None = None
    allowed_emails: frozenset[str] = frozenset()
    google_client_id: str | None = None
    google_client_secret: str | None = None
    telemetry: bool = True

    @property
    def vaults_dir(self) -> Path:
        return self.data_root / "vaults"

    @property
    def tokens_file(self) -> Path:
        return self.data_root / "tokens.yaml"

    @property
    def state_dir(self) -> Path:
        return self.data_root / "state"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if env is None else env

        def get(name: str) -> str | None:
            value = (env.get(name) or "").strip()
            return value or None

        data_root = get("MINDYARD_DATA_ROOT")
        if data_root is None:
            raise SettingsError("MINDYARD_DATA_ROOT is required (the directory holding the vaults)")
        port_raw = get("MINDYARD_PORT") or "8787"
        try:
            port = int(port_raw)
        except ValueError:
            raise SettingsError(f"MINDYARD_PORT={port_raw!r} is not a port number") from None
        emails = frozenset(
            e.strip().lower()
            for e in (get("MINDYARD_ALLOWED_EMAILS") or "").split(",")
            if e.strip()
        )
        settings = cls(
            data_root=Path(data_root).expanduser(),
            tenancy=_choice(env, "MINDYARD_TENANCY", "single", ("single", "mapped")),
            auth=_choice(env, "MINDYARD_AUTH", "none", ("none", "bearer", "google")),
            host=get("MINDYARD_HOST") or "127.0.0.1",
            port=port,
            path=get("MINDYARD_PATH") or "/mcp",
            base_url=(get("MINDYARD_BASE_URL") or "").rstrip("/") or None,
            allowed_emails=emails,
            google_client_id=get("MINDYARD_GOOGLE_CLIENT_ID"),
            google_client_secret=get("MINDYARD_GOOGLE_CLIENT_SECRET"),
            telemetry=(get("MINDYARD_TELEMETRY") or "1") != "0",
        )
        settings.check()
        return settings

    def check(self) -> None:
        """Refuse every combination that would expose the vaults."""
        if self.auth == "none" and not _is_loopback(self.host):
            raise SettingsError(
                f"MINDYARD_AUTH=none with MINDYARD_HOST={self.host}: an unauthenticated server may "
                "only listen on loopback. Pick an auth backend, or bind to 127.0.0.1."
            )
        if self.auth == "none" and self.tenancy == "mapped":
            raise SettingsError("MINDYARD_TENANCY=mapped needs an auth backend to identify callers")
        if self.auth == "google":
            values = (self.google_client_id, self.google_client_secret, self.base_url)
            missing = [name for name, v in zip(_GOOGLE_VARS, values, strict=True) if not v]
            if missing:
                raise SettingsError(f"MINDYARD_AUTH=google requires {', '.join(missing)}")
            if self.tenancy == "single" and not self.allowed_emails:
                raise SettingsError(
                    "MINDYARD_AUTH=google in single-tenant mode requires MINDYARD_ALLOWED_EMAILS: "
                    "without it, any Google account could read and write the vaults"
                )
