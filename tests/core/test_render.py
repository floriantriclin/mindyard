# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for display rendering (wikilink stripping) and read_page's raw flag."""

from __future__ import annotations

from pathlib import Path

from mindyard.core import operations
from mindyard.core.config import WikiSet
from mindyard.core.render import strip_wikilinks


def test_aliased_link_keeps_alias() -> None:
    assert (
        strip_wikilinks("lunch with [[ada-north|Ada North]] tomorrow")
        == "lunch with Ada North tomorrow"
    )


def test_bare_link_in_parens_is_removed() -> None:
    src = "notes from the reading group ([[2026-03-14-reading-group]])."
    assert strip_wikilinks(src) == "notes from the reading group."


def test_bare_link_inline_is_removed_and_spacing_tidied() -> None:
    assert strip_wikilinks("see [[wiki/entities/people/ada-north]] please") == ("see please")


def test_aliased_with_heading_target_keeps_alias() -> None:
    assert strip_wikilinks("[[note#section|Le point]] suit") == "Le point suit"


def test_embed_syntax_is_stripped() -> None:
    assert strip_wikilinks("![[diagram|Schéma]] ok") == "Schéma ok"


def test_plain_text_unchanged() -> None:
    text = "# Titre\n\nUn paragraphe sans lien.\n"
    assert strip_wikilinks(text) == text


def test_multiple_links_one_line() -> None:
    src = "avec [[a|Alice]] et [[b|Bob]] ([[ref-note]])"
    assert strip_wikilinks(src) == "avec Alice et Bob"


def test_bare_link_with_brackets_in_target_is_stripped() -> None:
    # A raw/ attachment whose filename carries brackets: excluding every bracket
    # left the whole "[[...]]" in the rendered output, which is exactly what
    # read_page promises never to show.
    src = "source [[raw/notes/[important] Note suivi dossiers_v07042026]] ok"
    assert strip_wikilinks(src) == "source ok"


def test_aliased_link_with_brackets_in_target_keeps_alias() -> None:
    src = "cf. [[raw/notes/[important] Note suivi|la note de suivi]] du 07/04"
    assert strip_wikilinks(src) == "cf. la note de suivi du 07/04"


def test_adjacent_links_do_not_merge() -> None:
    # Aliased, so a single match spanning both links would collapse to one alias
    # instead of two: the failure mode the old bracket exclusion guarded against.
    assert strip_wikilinks("[[a|Alice]][[b|Bob]] fin") == "AliceBob fin"


def _write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_read_page_renders_by_default(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    _write(wiki_roots["alpha"], "wiki/themes/x.md", "Note on [[c|Ada]].\n")
    view = operations.read_page(wikis["alpha"], "wiki/themes/x.md")
    assert view["content"] == "Note on Ada.\n"


def test_read_page_raw_returns_verbatim(wikis: WikiSet, wiki_roots: dict[str, Path]) -> None:
    raw = "Note on [[c|Ada]] ([[ref]]).\n"
    _write(wiki_roots["alpha"], "wiki/themes/x.md", raw)
    view = operations.read_page(wikis["alpha"], "wiki/themes/x.md", raw=True)
    assert view["content"] == raw
