# SPDX-License-Identifier: AGPL-3.0-or-later
"""Full-text search over a wiki, scoped to given subdirectories.

Prefers the ``rg`` (ripgrep) binary for speed and falls back to a pure-Python
scan when it is unavailable. Both paths are case-insensitive, restrict to
``*.md`` files, and return results with paths relative to the wiki root (POSIX
separators). ``regex=False`` (default) matches the query literally; ``regex=True``
treats it as a regular expression.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from typing_extensions import TypedDict

from .errors import InvalidRegexError


class SearchHit(TypedDict):
    page: str
    line: int
    text: str


def _rel_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _search_ripgrep(
    root: Path, subdirs: list[str], query: str, max_results: int, regex: bool
) -> list[SearchHit]:
    """Run ripgrep from ``root`` over ``subdirs`` and parse its output."""
    args = [
        "rg",
        "--line-number",
        "--ignore-case",
        "--no-heading",
        "--color=never",
        "--glob",
        "*.md",
    ]
    if not regex:
        args.append("--fixed-strings")
    args += ["--", query, *subdirs]

    try:
        # No stdin: over stdio the server's stdin is the MCP channel, and rg with a
        # piped stdin could read it. Bounded, like every subprocess here.
        proc = subprocess.run(
            args,
            cwd=str(root),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return _search_python(root, subdirs, query, max_results, regex)
    # rg exit codes: 0 = matches, 1 = no matches (not an error here), 2 = error
    # (e.g. an invalid regex when regex=True).
    if proc.returncode == 2:
        if regex:
            raise InvalidRegexError(query)
        return []
    if proc.returncode not in (0, 1):
        return []

    hits: list[SearchHit] = []
    for raw_line in proc.stdout.splitlines():
        # Format: "<relative-path>:<line>:<text>"
        parts = raw_line.split(":", 2)
        if len(parts) < 3:
            continue
        page, line_str, text = parts
        try:
            line_no = int(line_str)
        except ValueError:
            continue
        hits.append(SearchHit(page=Path(page).as_posix(), line=line_no, text=text.strip()))
        if len(hits) >= max_results:
            break
    return hits


def _search_python(
    root: Path, subdirs: list[str], query: str, max_results: int, regex: bool
) -> list[SearchHit]:
    """Pure-Python fallback: walk ``*.md`` files and scan lines."""
    if regex:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as exc:
            raise InvalidRegexError(query) from exc

        def matches(text: str) -> bool:
            return pattern.search(text) is not None
    else:
        needle = query.lower()

        def matches(text: str) -> bool:
            return needle in text.lower()

    hits: list[SearchHit] = []
    for subdir in subdirs:
        base = root / subdir
        if not base.exists():
            continue
        for md in sorted(base.rglob("*.md")):
            try:
                content = md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, text in enumerate(content.splitlines(), start=1):
                if matches(text):
                    hits.append(
                        SearchHit(
                            page=_rel_posix(root, md),
                            line=lineno,
                            text=text.strip(),
                        )
                    )
                    if len(hits) >= max_results:
                        return hits
    return hits


def search(
    root: Path,
    subdirs: list[str],
    query: str,
    max_results: int = 30,
    regex: bool = False,
) -> list[SearchHit]:
    """Search ``subdirs`` under ``root`` for ``query``; ripgrep with fallback."""
    if shutil.which("rg") is not None:
        return _search_ripgrep(root, subdirs, query, max_results, regex)
    return _search_python(root, subdirs, query, max_results, regex)
