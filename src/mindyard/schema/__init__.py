# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vault configuration: ``wiki.yaml`` model, loading and discovery."""

from .discovery import Wiki, discover_wikis
from .manifest import (
    ManifestError,
    WikiManifest,
    check_definition,
    load_manifest,
    parse_manifest,
)

__all__ = [
    "ManifestError",
    "Wiki",
    "WikiManifest",
    "check_definition",
    "discover_wikis",
    "load_manifest",
    "parse_manifest",
]
