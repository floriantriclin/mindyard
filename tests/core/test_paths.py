# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the path confinement helper: the critical security boundary.

Covers: traversal (``..``) rejected, confinement enforced per wiki
root, and no cross-wiki contamination.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mindyard.core.errors import PathEscapeError
from mindyard.core.paths import resolve_within


def test_simple_relative_path_resolves(tmp_path: Path) -> None:
    root = tmp_path / "alpha"
    root.mkdir()
    resolved = resolve_within(root, "wiki/page.md")
    assert resolved == (root / "wiki" / "page.md").resolve()


def test_nested_relative_path_resolves(tmp_path: Path) -> None:
    root = tmp_path / "alpha"
    root.mkdir()
    resolved = resolve_within(root, "wiki/themes/ai.md")
    assert resolved.is_relative_to(root.resolve())


@pytest.mark.parametrize(
    "bad_path",
    [
        "../escape.md",
        "../../etc/passwd",
        "wiki/../../escape.md",
        "wiki/../../../../../../etc/passwd",
        "./../sibling/x.md",
    ],
)
def test_parent_traversal_rejected(tmp_path: Path, bad_path: str) -> None:
    root = tmp_path / "alpha"
    root.mkdir()
    (tmp_path / "sibling").mkdir()
    with pytest.raises(PathEscapeError):
        resolve_within(root, bad_path)


@pytest.mark.parametrize(
    "abs_path",
    [
        "/etc/passwd",
        "/srv/wikis/beta/index.md",
        r"C:\Windows\System32\x.md",
        "C:/Windows/x.md",
        r"\\server\share\x.md",
        "C:relative.md",
    ],
)
def test_absolute_paths_rejected(tmp_path: Path, abs_path: str) -> None:
    root = tmp_path / "alpha"
    root.mkdir()
    with pytest.raises(PathEscapeError):
        resolve_within(root, abs_path)


@pytest.mark.parametrize("empty", ["", "   ", "\t"])
def test_empty_path_rejected(tmp_path: Path, empty: str) -> None:
    root = tmp_path / "alpha"
    root.mkdir()
    with pytest.raises(PathEscapeError):
        resolve_within(root, empty)


def test_no_cross_wiki_contamination(tmp_path: Path) -> None:
    """A path from one wiki must never resolve under another wiki root."""
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    with pytest.raises(PathEscapeError):
        resolve_within(alpha, "../beta/wiki/secret.md")


def test_traversal_back_into_root_still_confined(tmp_path: Path) -> None:
    """A path that wanders out and back in stays valid (still under root)."""
    root = tmp_path / "alpha"
    (root / "wiki").mkdir(parents=True)
    resolved = resolve_within(root, "wiki/../index.md")
    assert resolved == (root / "index.md").resolve()
