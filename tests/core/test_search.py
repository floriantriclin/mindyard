# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for search_wiki, covering both the ripgrep and pure-Python paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from mindyard.core import operations
from mindyard.core.config import WikiSet
from mindyard.core.errors import InvalidRegexError, InvalidScopeError


def _seed(root: Path) -> None:
    (root / "wiki" / "themes").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "themes" / "ai.md").write_text(
        "# AI\nMachine learning is everywhere.\nUnrelated line.\n",
        encoding="utf-8",
    )
    (root / "wiki" / "concepts.md").write_text("Deep MACHINE reasoning.\n", encoding="utf-8")
    (root / "raw" / "note.md").write_text("raw machine note\n", encoding="utf-8")


def test_search_finds_case_insensitive(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _seed(wiki_roots["alpha"])
    hits = operations.search_wiki(wikis["alpha"], "machine", scope="wiki")
    pages = {h["page"] for h in hits}
    assert pages == {"wiki/themes/ai.md", "wiki/concepts.md"}
    for h in hits:
        assert h["line"] >= 1
        assert "machine" in h["text"].lower()


def test_search_scope_excludes_raw_by_default(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _seed(wiki_roots["alpha"])
    hits = operations.search_wiki(wikis["alpha"], "machine", scope="wiki")
    assert all(not h["page"].startswith("raw/") for h in hits)


def test_search_all_scope_includes_raw(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _seed(wiki_roots["alpha"])
    hits = operations.search_wiki(wikis["alpha"], "machine", scope="all")
    assert any(h["page"] == "raw/note.md" for h in hits)


def test_search_respects_max_results(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _seed(wiki_roots["alpha"])
    hits = operations.search_wiki(wikis["alpha"], "machine", scope="all", max_results=1)
    assert len(hits) == 1


def test_search_invalid_scope_raises(wikis: WikiSet) -> None:
    with pytest.raises(InvalidScopeError):
        operations.search_wiki(wikis["alpha"], "x", scope="bogus")


def test_python_fallback_matches_ripgrep(
    wikis: WikiSet,
    wiki_roots: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forcing the no-ripgrep path yields the same matches."""
    _seed(wiki_roots["alpha"])
    monkeypatch.setattr("mindyard.core.search.shutil.which", lambda _name: None)
    hits = operations.search_wiki(wikis["alpha"], "machine", scope="wiki")
    pages = {h["page"] for h in hits}
    assert pages == {"wiki/themes/ai.md", "wiki/concepts.md"}


def test_search_scoped_no_contamination(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _seed(wiki_roots["alpha"])
    (wiki_roots["beta"] / "wiki").mkdir(parents=True, exist_ok=True)
    (wiki_roots["beta"] / "wiki" / "x.md").write_text("machine in beta\n", encoding="utf-8")
    hits = operations.search_wiki(wikis["alpha"], "machine", scope="all")
    assert all("beta" not in h["page"] for h in hits)


# --- regex flag -------------------------------------------------------------


def test_search_literal_by_default(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    """Without regex=True a regex metachar matches literally (no match here)."""
    _seed(wiki_roots["alpha"])
    hits = operations.search_wiki(wikis["alpha"], "mach.ne", scope="wiki")
    assert hits == []


def test_search_regex_matches(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _seed(wiki_roots["alpha"])
    hits = operations.search_wiki(wikis["alpha"], "mach.ne", scope="wiki", regex=True)
    pages = {h["page"] for h in hits}
    assert pages == {"wiki/themes/ai.md", "wiki/concepts.md"}


def test_search_invalid_regex_raises(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _seed(wiki_roots["alpha"])
    with pytest.raises(InvalidRegexError):
        operations.search_wiki(wikis["alpha"], "[unclosed", scope="wiki", regex=True)


def test_search_invalid_regex_raises_python_fallback(
    wikis: WikiSet,
    wiki_roots: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(wiki_roots["alpha"])
    monkeypatch.setattr("mindyard.core.search.shutil.which", lambda _name: None)
    with pytest.raises(InvalidRegexError):
        operations.search_wiki(wikis["alpha"], "[unclosed", scope="wiki", regex=True)
