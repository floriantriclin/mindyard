# SPDX-License-Identifier: AGPL-3.0-or-later
"""Discover the wikis under a directory: each subdirectory with a ``wiki.yaml``.

There is no central registry. A vault carries its own configuration, so moving
or sharing a vault never leaves its rules behind. Problems are collected rather
than raised one by one, so an operator sees every broken vault in one run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mindyard.core.config import CONFIG_FILE, WikiConfig
from mindyard.core.git import is_repo

from .manifest import ManifestError, WikiManifest, load_manifest


@dataclass(frozen=True)
class Wiki:
    """A discovered vault: the core's config plus the full manifest."""

    config: WikiConfig
    manifest: WikiManifest


def discover_wikis(base: Path) -> tuple[dict[str, Wiki], list[str]]:
    """Return ``({id: Wiki}, problems)`` for the vaults directly under ``base``.

    A vault must be a git repository: the server never runs ``git init`` on its
    own, that is an explicit step (``mindyard init``). A broken vault is reported
    and skipped; the caller decides whether a problem is fatal.
    """
    wikis: dict[str, Wiki] = {}
    problems: list[str] = []
    if not base.is_dir():
        return wikis, [f"{base}: not a directory"]
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not (child / CONFIG_FILE).is_file():
            continue
        try:
            manifest = load_manifest(child)
        except ManifestError as exc:
            problems.append(str(exc))
            continue
        if not is_repo(child):
            problems.append(f"{child}: not a git repository (run 'git init' or 'mindyard init')")
            continue
        root = child.resolve()
        wikis[child.name] = Wiki(manifest.to_config(child.name, root), manifest)
    return wikis, problems
