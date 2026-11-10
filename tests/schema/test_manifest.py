# SPDX-License-Identifier: AGPL-3.0-or-later
"""wiki.yaml: strict validation, defaults, id rules, discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from mindyard.schema import ManifestError, discover_wikis, load_manifest
from tests.conftest import git_init, make_wiki

MINIMAL = "mindyard: 1\nlabel: Reading notes\n"


def _vault(base: Path, name: str, manifest: str = MINIMAL, git: bool = True) -> Path:
    root = base / name
    make_wiki(root)
    (root / "wiki.yaml").write_text(manifest, encoding="utf-8")
    if git:
        git_init(root)
    return root


def test_minimal_manifest_gets_defaults(tmp_path: Path) -> None:
    root = _vault(tmp_path, "notes", git=False)
    manifest = load_manifest(root)
    cfg = manifest.to_config("notes", root)
    assert (cfg.wiki_dir, cfg.raw_dir, cfg.index_file, cfg.log_file, cfg.schema_file) == (
        "wiki",
        "raw",
        "index.md",
        "log.md",
        "schema.md",
    )
    assert cfg.log_sentinel == "<!-- log-end -->"
    assert manifest.lint.index_entry_max_chars == 250


def test_full_manifest(tmp_path: Path) -> None:
    root = _vault(
        tmp_path,
        "notes",
        """\
mindyard: 1
id: notes
label: Reading notes
description: Books, articles and the ideas they sparked.
layout: {wiki_dir: pages, schema: SCHEMA.md}
log: {timestamp: "%Y-%m-%d %H:%M"}
entities:
  book: {required: [title, author], status: [to-read, reading, read]}
  talk:
    status: [upcoming, ongoing, past]
    status_from_dates: {start: date, end: null}
lint:
  orphans: {exempt: ["pages/_inbox/**"]}
  index_entry_max_chars: null
""",
        git=False,
    )
    manifest = load_manifest(root)
    cfg = manifest.to_config("notes", root)
    assert cfg.wiki_dir == "pages"
    assert cfg.schema_file == "SCHEMA.md"
    assert cfg.description.startswith("Books")
    assert manifest.entities["book"].required == ["title", "author"]
    assert manifest.entities["talk"].status_from_dates is not None
    assert manifest.lint.index_entry_max_chars is None


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("mindyard: 2\nlabel: x\n", "mindyard"),
        ("mindyard: 1\n", "label"),
        ("mindyard: 1\nlabel: x\nlayot: {}\n", "layot"),
        ("mindyard: 1\nlabel: x\nlayout: {wiki_dir: ../escape}\n", "layout.wiki_dir"),
        ("mindyard: 1\nlabel: x\nlayout: {raw_dir: /abs}\n", "layout.raw_dir"),
        ("mindyard: 1\nlabel: x\nlint: {orphans: {exempted: []}}\n", "exempted"),
        (
            "mindyard: 1\nlabel: x\nentities: {e: {status_from_dates: {}}}\n",
            "requires a closed 'status'",
        ),
        (
            "mindyard: 1\nlabel: x\nentities: {e: {status: [a], status_from_dates: {}}}\n",
            "not in 'status'",
        ),
        ("- a list\n", "mapping"),
        ("mindyard: [1\n", "YAML"),
    ],
)
def test_invalid_manifest_names_the_field(tmp_path: Path, body: str, fragment: str) -> None:
    root = _vault(tmp_path, "notes", body, git=False)
    with pytest.raises(ManifestError, match=r"wiki\.yaml") as info:
        load_manifest(root)
    assert fragment in str(info.value)


def test_id_must_match_directory(tmp_path: Path) -> None:
    root = _vault(tmp_path, "notes", "mindyard: 1\nid: other\nlabel: x\n", git=False)
    with pytest.raises(ManifestError, match="does not match"):
        load_manifest(root)


def test_directory_name_must_be_a_valid_id(tmp_path: Path) -> None:
    root = _vault(tmp_path, "Bad Name", git=False)
    with pytest.raises(ManifestError, match="not a valid wiki id"):
        load_manifest(root)


def test_discovery_finds_vaults_and_reports_problems(tmp_path: Path) -> None:
    _vault(tmp_path, "notes")
    _vault(tmp_path, "garden")
    _vault(tmp_path, "nogit", git=False)
    _vault(tmp_path, "broken", "mindyard: 1\n")
    (tmp_path / "not-a-vault").mkdir()
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")

    wikis, problems = discover_wikis(tmp_path)

    assert sorted(wikis) == ["garden", "notes"]
    assert wikis["notes"].config.root == (tmp_path / "notes").resolve()
    assert len(problems) == 2
    assert any("nogit" in p and "git repository" in p for p in problems)
    assert any("broken" in p and "label" in p for p in problems)


def test_discovery_of_missing_base(tmp_path: Path) -> None:
    wikis, problems = discover_wikis(tmp_path / "absent")
    assert wikis == {}
    assert problems and "not a directory" in problems[0]
