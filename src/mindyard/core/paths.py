# SPDX-License-Identifier: AGPL-3.0-or-later
"""Path confinement: the critical multi-wiki security boundary.

Every user-supplied path is resolved against its wiki root and must stay under
that root. A confinement bug here would let one wiki's operation reach another
wiki's files, so this module is deliberately small, pure (no network I/O) and
unit-tested in isolation.

Cross-platform note: mindyard may run on Windows or POSIX, and
``Path.is_absolute`` is flavour-dependent: ``/etc/passwd`` is *not*
absolute to ``PureWindowsPath`` (no drive), and ``C:\\x`` is not absolute to
``PurePosixPath``. We therefore test both flavours so neither environment lets
an absolute path slip through.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from .errors import PathEscapeError


def _has_anchor(user_path: str) -> bool:
    """True if ``user_path`` is absolute or drive-qualified in any OS flavour.

    Catches POSIX-absolute (``/etc/...``), Windows-absolute (``C:\\...``),
    UNC (``\\\\server\\share``) and drive-relative (``C:foo``) forms.
    """
    win = PureWindowsPath(user_path)
    return (
        PurePosixPath(user_path).is_absolute()
        or win.is_absolute()
        or bool(win.drive)
        or bool(win.root)
    )


def resolve_within(root: Path, user_path: str) -> Path:
    """Resolve ``user_path`` under ``root`` and confirm it stays inside.

    Returns the resolved absolute path on success. Raises ``PathEscapeError``
    for empty input, any absolute/drive-qualified path, or any path that
    escapes ``root`` after normalisation (e.g. via ``..``).
    """
    if not user_path or not user_path.strip():
        raise PathEscapeError(user_path)

    if _has_anchor(user_path):
        raise PathEscapeError(user_path)

    candidate = (root / user_path).resolve()
    root_resolved = root.resolve()

    if not candidate.is_relative_to(root_resolved):
        raise PathEscapeError(user_path)

    return candidate
