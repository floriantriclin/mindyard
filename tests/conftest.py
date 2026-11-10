# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared fixtures: isolated, fictitious wiki roots under ``tmp_path``.

Two wikis (``alpha`` and ``beta``) side by side, so confinement and
non-contamination can be asserted across roots.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from mindyard.core.config import WikiConfig, WikiSet

WIKI_IDS = ("alpha", "beta")


def make_wiki(root: Path) -> None:
    """Create the standard wiki skeleton under ``root``."""
    (root / "raw").mkdir(parents=True)
    (root / "wiki").mkdir(parents=True)
    (root / "index.md").write_text("# Index\n", encoding="utf-8")
    (root / "log.md").write_text("# Log\n\n<!-- log-end -->\n", encoding="utf-8")
    (root / "schema.md").write_text("# Schema\n", encoding="utf-8")


def git_init(root: Path) -> None:
    """Initialise a git repo in ``root`` with an initial commit."""

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args], check=True)

    git("init", "-q")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "mindyard-test")
    git("add", "-A")
    git("commit", "-q", "-m", "initial")


@pytest.fixture
def wiki_roots(tmp_path: Path) -> dict[str, Path]:
    """Two bare (non-git) wiki skeletons keyed by id."""
    roots: dict[str, Path] = {}
    for wiki_id in WIKI_IDS:
        root = tmp_path / wiki_id
        make_wiki(root)
        roots[wiki_id] = root
    return roots


@pytest.fixture
def wikis(wiki_roots: dict[str, Path]) -> WikiSet:
    """The two temporary wikis as the core sees them."""
    return WikiSet(
        {
            wiki_id: WikiConfig(id=wiki_id, root=root, label=f"Wiki {wiki_id}")
            for wiki_id, root in wiki_roots.items()
        }
    )


@pytest.fixture
def git_wiki_roots(wiki_roots: dict[str, Path]) -> dict[str, Path]:
    """Same wiki skeletons, each an initialised git repo."""
    if shutil.which("git") is None:
        pytest.skip("git binary not available")
    for root in wiki_roots.values():
        git_init(root)
    return wiki_roots
