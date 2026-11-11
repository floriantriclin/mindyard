# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the read operations: read_page, list_pages."""

from __future__ import annotations

from pathlib import Path

import pytest

from mindyard.core import operations
from mindyard.core.config import WikiSet
from mindyard.core.errors import (
    InvalidScopeError,
    PageNotFoundError,
    PathEscapeError,
    UnknownWikiError,
)
from mindyard.core.operations import AUTO_PAGE_LIMIT, content_version


def _write(root: Path, rel: str, content: str = "x\n") -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


# --- read_page (PageView) ---------------------------------------------------


def test_read_page_returns_pageview(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _write(wiki_roots["alpha"], "wiki/themes/ai.md", "# AI\n")
    view = operations.read_page(wikis["alpha"], "wiki/themes/ai.md")
    assert view["content"] == "# AI\n"
    assert view["total_lines"] == 1
    assert view["start_line"] == 1
    assert view["end_line"] == 1
    assert view["truncated"] is False
    assert view["version"] == content_version("# AI\n")


def test_read_page_version_stable_raw_vs_rendered(
    wikis: WikiSet, wiki_roots: dict[str, Path]
) -> None:
    """version is computed on the raw bytes, so raw and rendered reads agree."""
    raw = "See [[c|Ada]] here.\n"
    _write(wiki_roots["alpha"], "wiki/p.md", raw)
    rendered_view = operations.read_page(wikis["alpha"], "wiki/p.md")
    raw_view = operations.read_page(wikis["alpha"], "wiki/p.md", raw=True)
    assert rendered_view["version"] == raw_view["version"] == content_version(raw)
    # But content differs: rendered strips the wikilink, raw keeps it.
    assert rendered_view["content"] == "See Ada here.\n"
    assert raw_view["content"] == raw


def test_read_page_version_changes_after_write(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    alpha = git_wiki_roots["alpha"]
    _write(alpha, "wiki/p.md", "v1\n")
    v1 = operations.read_page(wikis["alpha"], "wiki/p.md")["version"]
    _write(alpha, "wiki/p.md", "v2\n")
    v2 = operations.read_page(wikis["alpha"], "wiki/p.md")["version"]
    assert v1 != v2


def test_read_page_offset_and_limit(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _write(wiki_roots["alpha"], "wiki/p.md", "l1\nl2\nl3\nl4\nl5\n")
    view = operations.read_page(wikis["alpha"], "wiki/p.md", offset=2, limit=2)
    assert view["content"] == "l2\nl3\n"
    assert view["start_line"] == 2
    assert view["end_line"] == 3
    assert view["total_lines"] == 5
    assert view["truncated"] is True


def test_read_page_offset_beyond_end_is_empty(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _write(wiki_roots["alpha"], "wiki/p.md", "l1\nl2\n")
    view = operations.read_page(wikis["alpha"], "wiki/p.md", offset=10)
    assert view["content"] == ""
    assert view["total_lines"] == 2
    assert view["truncated"] is False


def test_read_page_line_count_raw_equals_rendered(
    wikis: WikiSet, wiki_roots: dict[str, Path]
) -> None:
    """Wikilink stripping is intra-line, so line counts match across modes."""
    _write(wiki_roots["alpha"], "wiki/p.md", "a [[x]]\nb [[y|Y]]\nc\n")
    rendered = operations.read_page(wikis["alpha"], "wiki/p.md")
    raw = operations.read_page(wikis["alpha"], "wiki/p.md", raw=True)
    assert rendered["total_lines"] == raw["total_lines"] == 3


def test_read_page_auto_paginates_long_file(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    body = "".join(f"line {i}\n" for i in range(AUTO_PAGE_LIMIT + 50))
    _write(wiki_roots["alpha"], "wiki/long.md", body)
    view = operations.read_page(wikis["alpha"], "wiki/long.md")
    assert view["total_lines"] == AUTO_PAGE_LIMIT + 50
    assert view["end_line"] == AUTO_PAGE_LIMIT
    assert view["truncated"] is True


def test_read_page_missing_raises(wikis: WikiSet) -> None:
    with pytest.raises(PageNotFoundError):
        operations.read_page(wikis["alpha"], "wiki/nope.md")


def test_read_page_unknown_wiki_raises(wikis: WikiSet) -> None:
    with pytest.raises(UnknownWikiError):
        wikis.get_wiki("zzz")


def test_read_page_traversal_rejected(wikis: WikiSet) -> None:
    with pytest.raises(PathEscapeError):
        operations.read_page(wikis["alpha"], "../beta/index.md")


# --- list_pages (PageList) --------------------------------------------------


def test_list_pages_wiki_scope(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _write(wiki_roots["alpha"], "wiki/a.md")
    _write(wiki_roots["alpha"], "wiki/themes/b.md")
    _write(wiki_roots["alpha"], "raw/c.md")
    result = operations.list_pages(wikis["alpha"], scope="wiki")
    assert result["pages"] == ["wiki/a.md", "wiki/themes/b.md"]
    assert result["total"] == 2
    assert result["truncated"] is False


def test_list_pages_all_scope_includes_raw(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _write(wiki_roots["alpha"], "wiki/a.md")
    _write(wiki_roots["alpha"], "raw/c.md")
    result = operations.list_pages(wikis["alpha"], scope="all")
    assert result["pages"] == ["raw/c.md", "wiki/a.md"]


def test_list_pages_prefix_filter(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _write(wiki_roots["alpha"], "wiki/themes/ai.md")
    _write(wiki_roots["alpha"], "wiki/concepts/x.md")
    result = operations.list_pages(wikis["alpha"], scope="wiki", prefix="wiki/themes")
    assert result["pages"] == ["wiki/themes/ai.md"]


def test_list_pages_limit_truncates(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    for i in range(5):
        _write(wiki_roots["alpha"], f"wiki/p{i}.md")
    result = operations.list_pages(wikis["alpha"], scope="wiki", limit=3)
    assert len(result["pages"]) == 3
    assert result["total"] == 5
    assert result["truncated"] is True


def test_list_pages_invalid_scope_raises(wikis: WikiSet) -> None:
    with pytest.raises(InvalidScopeError):
        operations.list_pages(wikis["alpha"], scope="everything")


def test_list_pages_scoped_to_wiki_only(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    """Pages from one wiki never leak into another's listing."""
    _write(wiki_roots["alpha"], "wiki/alpha-page.md")
    _write(wiki_roots["beta"], "wiki/beta-page.md")
    assert operations.list_pages(wikis["alpha"])["pages"] == ["wiki/alpha-page.md"]
    assert operations.list_pages(wikis["beta"])["pages"] == ["wiki/beta-page.md"]
