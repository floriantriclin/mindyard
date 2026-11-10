# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure Markdown helpers for the linter: links and frontmatter. No disk."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any

import yaml

# Same link grammar as the renderer: the shortest same-line run without "]]",
# so a target carrying a single bracket (a raw attachment name) still counts.
_LINK_INNER = r"(?:(?!\]\])[^\n])+?"
WIKILINK_RE = re.compile(rf"\[\[({_LINK_INNER})\]\]")
UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")

_FENCED_CODE_RE = re.compile(r"(?ms)^[ \t]*(`{3,}|~{3,}).*?^[ \t]*\1[ \t]*$")
_INLINE_CODE_RE = re.compile(r"(`+)[^\n]*?\1")
_BOM = "﻿"


def strip_code(text: str) -> str:
    """Blank out code blocks and spans: a link shown in code is an example."""
    return _INLINE_CODE_RE.sub("", _FENCED_CODE_RE.sub("\n", text))


def link_targets(text: str) -> list[str]:
    """Targets of every wikilink outside code, without alias or heading.

    A table-escaped pipe (``\\|``) is unescaped first, so ``[[a\\|b]]`` is ``a``.
    Pure-heading links (``[[#section]]``) yield nothing.
    """
    targets: list[str] = []
    for match in WIKILINK_RE.finditer(strip_code(text)):
        inner = match.group(1).replace("\\|", "|")
        target = inner.split("|", 1)[0].split("#", 1)[0].strip()
        if target:
            targets.append(target)
    return targets


def link_key(target: str) -> str:
    """How a link target is matched: basename, lower-cased, without ``.md``."""
    tail = target.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return tail[:-3].lower() if tail.lower().endswith(".md") else tail.lower()


def file_stem_key(rel: str) -> str:
    """How a file is matched by a link: its stem, lower-cased."""
    return PurePosixPath(rel).stem.lower()


def is_file_ref(target: str) -> bool:
    """True if a link names a concrete file (a raw path, a non-Markdown file).

    Such a link that resolves nowhere is broken. A bare page name that resolves
    nowhere is a page not written yet: a backlog item, not an error.
    """
    norm = target.replace("\\", "/").rstrip("/")
    return norm.lower().startswith("raw/") or PurePosixPath(norm).suffix.lower() not in ("", ".md")


class FrontmatterError(ValueError):
    pass


def frontmatter(text: str) -> dict[str, Any] | None:
    """The leading YAML block as a mapping, ``None`` if there is none.

    Raises :class:`FrontmatterError` for a block that is not valid YAML or not a
    mapping: a page that tried to declare metadata and failed is worth flagging.
    A UTF-8 BOM before the opening ``---`` is tolerated.
    """
    lines = text.lstrip(_BOM).splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        return None
    try:
        data = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise FrontmatterError(str(exc).splitlines()[0]) from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise FrontmatterError("frontmatter is not a mapping")
    return data


def as_date(value: object) -> date | None:
    """A frontmatter value as a date, ``None`` if absent or unparseable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None
