# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for git operations: commit and rollback."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mindyard.core.git import commit_files, head_sha, is_repo, rollback


def test_is_repo_true_for_git_root(git_wiki_roots: dict[str, Path]) -> None:
    assert is_repo(git_wiki_roots["alpha"]) is True


def test_is_repo_false_for_plain_dir(wiki_roots: dict[str, Path]) -> None:
    assert is_repo(wiki_roots["alpha"]) is False


def test_commit_files_creates_one_commit(git_wiki_roots: dict[str, Path]) -> None:
    root = git_wiki_roots["alpha"]
    before = head_sha(root)
    (root / "wiki" / "new.md").write_text("# New\n", encoding="utf-8")
    sha = commit_files(root, ["wiki/new.md"], "add new page")
    after = head_sha(root)
    assert sha == after
    assert before != after


def test_rollback_restores_tracked_and_removes_created(
    git_wiki_roots: dict[str, Path],
) -> None:
    root = git_wiki_roots["alpha"]
    start = head_sha(root)
    # Simulate a partially written batch: one new file, one modified tracked file.
    created = "wiki/created.md"
    (root / created).write_text("# Created\n", encoding="utf-8")
    (root / "index.md").write_text("# Index modified\n", encoding="utf-8")

    rollback(root, start, [created])

    assert head_sha(root) == start
    assert not (root / created).exists()
    # Tracked file restored to its committed content.
    assert (root / "index.md").read_text(encoding="utf-8") == "# Index\n"


def test_head_sha_stable(git_wiki_roots: dict[str, Path]) -> None:
    root = git_wiki_roots["alpha"]
    assert head_sha(root) == head_sha(root)


def test_commit_falls_back_to_a_mindyard_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A vault with no git identity anywhere can still be written."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "none"))
    root = tmp_path / "vault"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    (root / "a.md").write_text("a\n", encoding="utf-8")
    commit_files(root, ["a.md"], "first")
    author = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%an <%ae>"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert author == "mindyard <mindyard@localhost>"
