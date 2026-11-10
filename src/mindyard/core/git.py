# SPDX-License-Identifier: AGPL-3.0-or-later
"""Git operations for ``write_batch``: atomic commit and rollback.

Uses the ``git`` binary via ``subprocess`` (no GitPython): git is already a
container dependency, args are passed as lists (never ``shell=True``), and every
call is scoped with ``git -C <root>`` so it never depends on the process cwd.

The server is the sole, serialised writer, so the worktree is clean before each
batch. Rollback therefore discards the failed batch with ``reset --hard`` plus a
targeted removal of newly created (untracked) files, see ``rollback``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import GitError


def _run(root: Path, *args: str) -> str:
    """Run ``git -C <root> <args>`` and return stdout, or raise ``GitError``."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def is_repo(root: Path) -> bool:
    """True if ``root`` contains a git repository."""
    return (root / ".git").exists()


def head_sha(root: Path) -> str:
    """Return the current HEAD short sha."""
    return _run(root, "rev-parse", "--short", "HEAD")


def commit_files(root: Path, rel_paths: list[str], message: str, author: str | None = None) -> str:
    """Stage ``rel_paths`` and create a single commit; return its short sha.

    Paths are relative to ``root``. ``author`` (``Name <email>``) sets the
    commit author; the committer stays the repository's identity. Raises
    ``GitError`` on any git failure.
    """
    _run(root, "add", "--", *rel_paths)
    author_args = ["--author", author] if author else []
    _run(root, *_fallback_identity(root), "commit", *author_args, "-m", message)
    return head_sha(root)


FALLBACK_NAME = "mindyard"
FALLBACK_EMAIL = "mindyard@localhost"


def _fallback_identity(root: Path) -> list[str]:
    """Commit as ``mindyard`` only where git has no identity configured.

    A vault owner's own ``user.name``/``user.email`` (repo, global or system)
    always wins; a bare container or a fresh machine must still be able to
    commit rather than fail every write.
    """
    probe = subprocess.run(
        ["git", "-C", str(root), "config", "user.email"], capture_output=True, text=True
    )
    if probe.returncode == 0 and probe.stdout.strip():
        return []
    return ["-c", f"user.name={FALLBACK_NAME}", "-c", f"user.email={FALLBACK_EMAIL}"]


def rollback(root: Path, start_sha: str, created: list[str]) -> None:
    """Discard a failed batch: reset to ``start_sha`` and delete created files.

    ``reset --hard`` restores tracked files but leaves untracked ones in place,
    so newly created files from the batch are removed explicitly (rather than a
    blanket ``git clean`` that could touch unrelated untracked files).
    """
    _run(root, "reset", "--hard", start_sha)
    for rel in created:
        target = root / rel
        if target.exists():
            target.unlink()
