# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write-time normalisation: table-cell pipes in aliased wikilinks.

An aliased wikilink inside a Markdown table cell must escape its pipe
(``[[a\\|b]]``), or the bare ``|`` is read as a column separator and breaks both
the table and the link. Models forget this constantly, so the server fixes it on
write rather than rejecting the batch (an atomic batch carrying a whole page
should not have to be regenerated over a missing backslash).

The rewrite must be: correct in a table, inert outside one, idempotent, and never
applied to ``raw/``: which holds verbatim sources.
"""

from __future__ import annotations

from pathlib import Path

from mindyard.core.config import WikiSet
from mindyard.core.operations import read_page, write_batch
from mindyard.core.render import escape_table_pipes

# --- the pure function ------------------------------------------------------


def test_escapes_pipe_in_table_cell() -> None:
    text = "| a | [[target|alias]] |\n"
    out, n = escape_table_pipes(text)
    assert out == "| a | [[target\\|alias]] |\n"
    assert n == 1


def test_leaves_links_outside_tables_alone() -> None:
    """Outside a table the bare pipe is correct: escaping it would be wrong."""
    text = "Voir [[target|alias]] dans le texte.\n"
    out, n = escape_table_pipes(text)
    assert out == text
    assert n == 0


def test_leaves_already_escaped_alone() -> None:
    text = "| a | [[target\\|alias]] |\n"
    out, n = escape_table_pipes(text)
    assert out == text
    assert n == 0


def test_leaves_cell_separators_alone() -> None:
    """Only pipes *inside* [[...]] are touched, never the column separators."""
    text = "| [[a\\|x]] | plain | [[b]] |\n"
    out, n = escape_table_pipes(text)
    assert out == text
    assert n == 0


def test_idempotent() -> None:
    once, n1 = escape_table_pipes("| [[a|x]] |\n")
    twice, n2 = escape_table_pipes(once)
    assert twice == once
    assert (n1, n2) == (1, 0)


def test_counts_every_link_on_the_row() -> None:
    text = "| [[a|x]] | [[b|y]] | [[c\\|z]] |\n"
    out, n = escape_table_pipes(text)
    assert n == 2
    assert out.count("\\|") == 3


def test_preserves_line_endings_and_bare_links() -> None:
    text = "| [[a|x]] |\r\n| [[b]] |\r\n"
    out, _ = escape_table_pipes(text)
    assert out == "| [[a\\|x]] |\r\n| [[b]] |\r\n"


# --- through write_batch ----------------------------------------------------


def test_write_batch_normalises_and_reports(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    """A page written with a bare table pipe lands on disk escaped, and says so."""
    result = write_batch(
        wikis["alpha"],
        [
            {
                "op": "create",
                "path": "wiki/pipes.md",
                "content": "# T\n\n| Item | Who |\n|---|---|\n| I1 | [[bo-river|River]] |\n",
            }
        ],
        "add page with an unescaped table pipe",
    )

    on_disk = read_page(wikis["alpha"], "wiki/pipes.md", raw=True)["content"]
    assert "[[bo-river\\|River]]" in on_disk
    assert "[[bo-river|River]]" not in on_disk

    # The fix is surfaced, not silent.
    assert result["normalized"] == [{"path": "wiki/pipes.md", "table_pipes": 1}]


def test_write_batch_reports_nothing_when_clean(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    result = write_batch(
        wikis["alpha"],
        [{"op": "create", "path": "wiki/clean.md", "content": "Voir [[a|b]].\n"}],
        "add clean page",
    )
    assert "normalized" not in result


def test_replace_result_is_normalised_too(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    """The fix applies to the *resulting* content, not just to whole-file writes."""
    write_batch(
        wikis["alpha"],
        [{"op": "create", "path": "wiki/t.md", "content": "| a |\n| SENTINEL |\n"}],
        "seed",
    )
    version = read_page(wikis["alpha"], "wiki/t.md", raw=True)["version"]
    write_batch(
        wikis["alpha"],
        [
            {
                "op": "replace",
                "path": "wiki/t.md",
                "old": "SENTINEL",
                "new": "[[x|y]]",
                "expected_version": version,
            }
        ],
        "replace into a table cell",
    )
    on_disk = read_page(wikis["alpha"], "wiki/t.md", raw=True)["content"]
    assert "[[x\\|y]]" in on_disk


def test_raw_is_never_normalised(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    """``raw/`` holds verbatim sources: the server must not touch a byte of them."""
    verbatim = "| col |\n| [[a|b]] |\n"
    write_batch(
        wikis["alpha"],
        [{"op": "create", "path": "raw/source.md", "content": verbatim}],
        "import a raw source",
    )
    on_disk = read_page(wikis["alpha"], "raw/source.md", raw=True)["content"]
    assert on_disk == verbatim  # unchanged, pipe still bare
