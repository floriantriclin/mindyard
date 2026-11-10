# SPDX-License-Identifier: AGPL-3.0-or-later
"""Linter: generic checks, declared rules, report, pipe fixer."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from mindyard.lint import fix_table_pipes, lint_wiki, render_report, write_report
from mindyard.lint.markdown import FrontmatterError, frontmatter, link_targets
from mindyard.schema import Wiki, load_manifest
from tests.conftest import make_wiki

TODAY = date(2026, 6, 15)

MANIFEST = """\
mindyard: 1
label: Reading notes
entities:
  book: {required: [title, author], status: [to-read, reading, read]}
  talk:
    status: [upcoming, ongoing, past]
    status_from_dates: {start: start_date, end: end_date}
lint:
  orphans: {exempt: ["wiki/_inbox/**"]}
  index_entry_max_chars: 80
"""

FM = "---\ntitle: x\n---\n"


def _wiki(root: Path, pages: dict[str, str], manifest: str = MANIFEST) -> Wiki:
    make_wiki(root)
    (root / "wiki.yaml").write_text(manifest, encoding="utf-8")
    for rel, text in pages.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    m = load_manifest(root)
    return Wiki(m.to_config(root.name, root), m)


def _rules(wiki: Wiki) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for f in lint_wiki(wiki, TODAY).items:
        out.setdefault(f.rule, []).append(f"{f.path}|{f.detail}" if f.detail else f.path)
    return out


def test_clean_wiki_has_nothing_to_report(tmp_path: Path) -> None:
    wiki = _wiki(
        tmp_path / "notes",
        {
            "index.md": "# Index\n- [[a]]\n",
            "wiki/a.md": FM + "See [[b]] and [[log]] and [[raw/src]].\n",
            "wiki/b.md": FM + "Back to [[a]].\n",
            "raw/src.pdf": "%PDF",
            "raw/.gitkeep": "",
        },
    )
    findings = lint_wiki(wiki, TODAY)
    assert findings.items == []
    assert (findings.pages_scanned, findings.raw_scanned) == (3, 1)
    assert "Nothing to report" in render_report(wiki, findings)


def test_generic_checks(tmp_path: Path) -> None:
    wiki = _wiki(
        tmp_path / "notes",
        {
            "index.md": "# Index\n- [[a]]\n- [[b]] " + "x" * 90 + "\n",
            "wiki/a.md": FM + "[[raw/missing.pdf]] [[future-page]] `[[in-code]]` [[a]]\n",
            "wiki/b.md": "no frontmatter, links [[a]]\n",
            "wiki/lonely.md": FM + "nobody links here\n",
            "wiki/_inbox/idea.md": FM + "exempt orphan\n",
            "wiki/table.md": FM + "| c |\n|---|\n| [[a|alias]] |\n",
            "wiki/bad.md": "---\ntitle: [unclosed\n---\n[[a]]\n",
            "raw/unused.txt": "x",
            "raw/cited.txt": "x",
            "wiki/cites.md": FM + "see raw/cited.txt [[cites]]\n",
        },
    )
    rules = _rules(wiki)
    assert rules["broken_link"] == ["wiki/a.md|raw/missing.pdf"]
    assert rules["unresolved_link"] == ["wiki/a.md|future-page"]
    assert sorted(rules["orphan"]) == [
        "wiki/bad.md",
        "wiki/cites.md",
        "wiki/lonely.md",
        "wiki/table.md",
    ]
    assert rules["missing_frontmatter"] == ["wiki/b.md"]
    assert [r.split("|")[0] for r in rules["invalid_frontmatter"]] == ["wiki/bad.md"]
    assert rules["unreferenced_raw"] == ["raw/unused.txt"]
    assert rules["table_pipe"] == ["wiki/table.md|[[a|alias]]"]
    assert rules["long_index_entry"][0].startswith("index.md|b (")
    findings = lint_wiki(wiki, TODAY)
    # Notices (unresolved link, long index entry) are not counted.
    assert findings.total == len(findings.items) - 2


@pytest.mark.parametrize(
    ("fm", "expected"),
    [
        ("entity_kind: book\ntitle: T\nauthor: A\nstatus: read", {}),
        ("entity_kind: book\ntitle: T\nstatus: read", {"missing_field": ["book: author"]}),
        (
            "entity_kind: book\ntitle: T\nauthor: A\nstatus: finished",
            {"invalid_status": ["book: 'finished'"]},
        ),
        ("entity_kind: unknown\nstatus: anything", {}),  # undeclared kinds are free
        ("entity_kind: talk\nstatus: upcoming\nstart_date: 2026-07-01", {}),
        ("entity_kind: talk\nstatus: ongoing\nstart_date: 2026-06-15", {}),
        (
            "entity_kind: talk\nstatus: upcoming\nstart_date: 2026-06-01\nend_date: 2026-06-10",
            {"status_date_conflict": ["'upcoming', dates imply 'past'"]},
        ),
        (
            "entity_kind: talk\nstatus: ongoing\nstart_date: 2026-06-01\nend_date: 2026-06-30",
            {},
        ),
        (
            "entity_kind: talk\nstatus: upcoming",
            {"status_date_conflict": ["no valid 'start_date' to check"]},
        ),
    ],
)
def test_declared_entity_rules(tmp_path: Path, fm: str, expected: dict[str, list[str]]) -> None:
    wiki = _wiki(
        tmp_path / "notes",
        {"index.md": "- [[p]]\n", "wiki/p.md": f"---\n{fm}\n---\nbody\n"},
    )
    got = {rule: [d.split("|", 1)[1] for d in v] for rule, v in _rules(wiki).items()}
    assert got == expected


def test_rules_not_declared_never_fire(tmp_path: Path) -> None:
    wiki = _wiki(
        tmp_path / "notes",
        {"index.md": "- [[p]] " + "x" * 300 + "\n", "wiki/p.md": "---\nstatus: whatever\n---\n"},
        manifest="mindyard: 1\nlabel: x\nlint: {index_entry_max_chars: null}\n",
    )
    assert lint_wiki(wiki, TODAY).items == []


def test_ignored_and_hidden_dirs_are_skipped(tmp_path: Path) -> None:
    wiki = _wiki(
        tmp_path / "notes",
        {
            "index.md": "- [[p]]\n",
            "wiki/p.md": FM,
            "wiki/.obsidian/x.md": "junk",
            "wiki/templates/t.md": "no fm",
        },
        manifest="mindyard: 1\nlabel: x\nlint: {ignored_dirs: [templates]}\n",
    )
    assert lint_wiki(wiki, TODAY).items == []


def test_bom_before_frontmatter_is_tolerated() -> None:
    assert frontmatter("﻿---\na: 1\n---\n") == {"a": 1}
    assert frontmatter("no block") is None
    assert frontmatter("---\nunclosed\n") is None
    with pytest.raises(FrontmatterError):
        frontmatter("---\n- a list\n---\n")


def test_link_targets_handle_alias_heading_and_escaped_pipe() -> None:
    text = "[[a|b]] [[c#h]] [[d\\|e]] [[#only]]\n```\n[[code]]\n```\n[[raw/[x] y]]"
    assert link_targets(text) == ["a", "c", "d", "raw/[x] y"]


def test_report_and_fixer(tmp_path: Path) -> None:
    wiki = _wiki(
        tmp_path / "notes",
        {"index.md": "- [[t]]\n", "wiki/t.md": FM + "| c |\n|---|\n| [[t|x]] [[t|y]] |\n"},
    )
    path = write_report(wiki, lint_wiki(wiki, TODAY))
    report = path.read_text(encoding="utf-8")
    assert path.name == "LINT_REPORT.md"
    assert "**2 issue(s)**" in report and "## Unescaped pipes" in report
    assert fix_table_pipes(wiki) == [("wiki/t.md", 2)]
    assert fix_table_pipes(wiki) == []
    assert lint_wiki(wiki, TODAY).items == []
