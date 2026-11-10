# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vault configuration: ``wiki.yaml`` model, loading and discovery."""

from .discovery import Wiki, discover_wikis
from .manifest import ManifestError, WikiManifest, load_manifest

__all__ = ["ManifestError", "Wiki", "WikiManifest", "discover_wikis", "load_manifest"]
