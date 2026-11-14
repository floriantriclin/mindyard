# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for write_batch typed ops: atomicity, rollback, raw/log rules, CAS.

Covers: create / overwrite / replace / delete / rename, the append
sentinel for log.md, optimistic concurrency (expected_version), and the
transactional guarantees (validate-all-then-write, rollback on failure).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mindyard.core import operations
from mindyard.core.config import WikiSet
from mindyard.core.errors import (
    ConfigLockedError,
    ConfigRejectedError,
    CreateExistsError,
    EmptyBatchError,
    GitError,
    OverwriteMissingError,
    PageNotFoundError,
    PathEscapeError,
    ProtectedFileError,
    RawImmutableError,
    RenameDestExistsError,
    ReplaceAmbiguousError,
    ReplaceNotFoundError,
    ReplaceTargetMissingError,
    StaleVersionError,
    UnknownOperationError,
    UnknownWikiError,
    VersionRequiredError,
    WriteZoneError,
)
from mindyard.core.operations import Operation, content_version


def _commit_count(root: Path) -> int:
    out = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout.strip())


def _version(root: Path, rel: str) -> str:
    """Content-version token of an on-disk file (what read_page would return)."""
    return content_version((root / rel).read_text(encoding="utf-8"))


# --- create -----------------------------------------------------------------


def test_create_makes_one_commit(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    before = _commit_count(alpha)
    result = operations.write_batch(
        wikis["alpha"],
        [Operation(op="create", path="wiki/new.md", content="# New\n")],
        "add new page",
    )
    assert _commit_count(alpha) == before + 1
    assert result["commit"]
    assert result["applied"] == [{"op": "create", "path": "wiki/new.md"}]
    assert (alpha / "wiki" / "new.md").read_text(encoding="utf-8") == "# New\n"


def test_create_fails_if_exists(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    before = _commit_count(alpha)
    with pytest.raises(CreateExistsError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="create", path="index.md", content="x\n")],
            "dup",
        )
    assert _commit_count(alpha) == before


def test_create_raw_allowed(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    operations.write_batch(
        wikis["alpha"],
        [Operation(op="create", path="raw/fresh.md", content="new\n")],
        "add raw",
    )
    assert (alpha / "raw" / "fresh.md").exists()


# --- overwrite --------------------------------------------------------------


def test_overwrite_succeeds_with_version(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    version = _version(alpha, "index.md")
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(
                op="overwrite",
                path="index.md",
                content="# Index v2\n",
                expected_version=version,
            )
        ],
        "rewrite index",
    )
    assert (alpha / "index.md").read_text(encoding="utf-8") == "# Index v2\n"


def test_overwrite_missing_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    with pytest.raises(OverwriteMissingError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="overwrite",
                    path="wiki/ghost.md",
                    content="x\n",
                    expected_version="deadbeef",
                )
            ],
            "no target",
        )


def test_overwrite_raw_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "raw" / "src.md").write_text("original\n", encoding="utf-8")
    with pytest.raises(RawImmutableError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="overwrite",
                    path="raw/src.md",
                    content="tampered\n",
                    expected_version="x",
                )
            ],
            "should fail",
        )
    assert (alpha / "raw" / "src.md").read_text(encoding="utf-8") == "original\n"


# --- replace ----------------------------------------------------------------


def test_replace_targeted_segment_is_byte_exact(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text(
        "# Title\nkeep [[link]] keep\nOLD line\ntail\n", encoding="utf-8"
    )
    version = _version(alpha, "wiki/p.md")
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(
                op="replace",
                path="wiki/p.md",
                old="OLD line",
                new="NEW line",
                expected_version=version,
            )
        ],
        "edit",
    )
    # Only the targeted bytes change; wikilink and everything else intact.
    assert (alpha / "wiki" / "p.md").read_text(encoding="utf-8") == (
        "# Title\nkeep [[link]] keep\nNEW line\ntail\n"
    )


def test_replace_old_not_found(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("hello\n", encoding="utf-8")
    version = _version(alpha, "wiki/p.md")
    with pytest.raises(ReplaceNotFoundError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="replace",
                    path="wiki/p.md",
                    old="absent",
                    new="x",
                    expected_version=version,
                )
            ],
            "miss",
        )


def test_replace_ambiguous(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("dup\ndup\n", encoding="utf-8")
    version = _version(alpha, "wiki/p.md")
    with pytest.raises(ReplaceAmbiguousError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="replace",
                    path="wiki/p.md",
                    old="dup",
                    new="x",
                    expected_version=version,
                )
            ],
            "ambiguous",
        )


def test_replace_all(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("dup\ndup\n", encoding="utf-8")
    version = _version(alpha, "wiki/p.md")
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(
                op="replace",
                path="wiki/p.md",
                old="dup",
                new="x",
                replace_all=True,
                expected_version=version,
            )
        ],
        "replace all",
    )
    assert (alpha / "wiki" / "p.md").read_text(encoding="utf-8") == "x\nx\n"


def test_replace_raw_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "raw" / "src.md").write_text("a\n", encoding="utf-8")
    with pytest.raises(RawImmutableError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="replace",
                    path="raw/src.md",
                    old="a",
                    new="b",
                    expected_version="x",
                )
            ],
            "raw replace",
        )


def test_replace_missing_target(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    with pytest.raises(ReplaceTargetMissingError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="replace",
                    path="wiki/ghost.md",
                    old="a",
                    new="b",
                    expected_version="x",
                )
            ],
            "no target",
        )


def test_two_chained_replaces_same_file(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    """The second replace sees the first one's result (MultiEdit semantics)."""
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("one two three\n", encoding="utf-8")
    version = _version(alpha, "wiki/p.md")
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(
                op="replace",
                path="wiki/p.md",
                old="one",
                new="1",
                expected_version=version,
            ),
            # Same version token: CAS is checked against the original on-disk
            # bytes, so two replaces on one file share a single token.
            Operation(
                op="replace",
                path="wiki/p.md",
                old="two",
                new="2",
                expected_version=version,
            ),
        ],
        "chained",
    )
    assert (alpha / "wiki" / "p.md").read_text(encoding="utf-8") == "1 2 three\n"


def test_replace_log_sentinel_appends_entry(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    """A log entry is added by replacing the <!-- log-end --> sentinel."""
    alpha = git_wiki_roots["alpha"]
    version = _version(alpha, "log.md")
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(
                op="replace",
                path="log.md",
                old="<!-- log-end -->",
                new="## [2026-06-14]\nIngested X.\n\n<!-- log-end -->",
                expected_version=version,
            )
        ],
        "log entry",
    )
    assert (alpha / "log.md").read_text(encoding="utf-8") == (
        "# Log\n\n## [2026-06-14]\nIngested X.\n\n<!-- log-end -->\n"
    )


# --- optimistic concurrency (CAS) -------------------------------------------


def test_replace_missing_version_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("a\n", encoding="utf-8")
    with pytest.raises(VersionRequiredError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="replace", path="wiki/p.md", old="a", new="b")],
            "no version",
        )


def test_stale_version_message_withholds_the_current_token(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    # Quoting the current version let a client retry the same edit with the
    # fresh token and no re-read, which is a lost update on overwrite/delete/
    # rename (no anchor to catch it). The token must stay server-side.
    alpha = git_wiki_roots["alpha"]
    page = alpha / "wiki" / "p.md"
    page.write_text("contenu courant\n", encoding="utf-8")
    current = operations.content_version(page.read_text(encoding="utf-8"))

    with pytest.raises(StaleVersionError) as caught:
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="overwrite",
                    path="wiki/p.md",
                    content="écrasé\n",
                    expected_version="0000staleversion",
                )
            ],
            "stale overwrite",
        )

    message = str(caught.value)
    assert current not in message
    assert "0000staleversion" in message  # the stale token is fine to echo back
    assert caught.value.actual == current  # kept for server-side diagnostics


def test_replace_stale_version_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("a\n", encoding="utf-8")
    before = _commit_count(alpha)
    with pytest.raises(StaleVersionError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="replace",
                    path="wiki/p.md",
                    old="a",
                    new="b",
                    expected_version="0000staleversion",
                )
            ],
            "stale",
        )
    assert _commit_count(alpha) == before
    assert (alpha / "wiki" / "p.md").read_text(encoding="utf-8") == "a\n"


def test_create_then_replace_same_batch_skips_cas(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    """A path created in the batch needs no version on a later replace."""
    alpha = git_wiki_roots["alpha"]
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(op="create", path="wiki/n.md", content="placeholder\n"),
            Operation(op="replace", path="wiki/n.md", old="placeholder", new="real"),
        ],
        "create+replace",
    )
    assert (alpha / "wiki" / "n.md").read_text(encoding="utf-8") == "real\n"


# --- delete -----------------------------------------------------------------


def test_delete_succeeds(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("bye\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(alpha), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(alpha), "commit", "-q", "-m", "seed"], check=True)
    version = _version(alpha, "wiki/p.md")
    result = operations.write_batch(
        wikis["alpha"],
        [Operation(op="delete", path="wiki/p.md", expected_version=version)],
        "remove",
    )
    assert result["applied"] == [{"op": "delete", "path": "wiki/p.md"}]
    assert not (alpha / "wiki" / "p.md").exists()


def test_delete_missing_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    with pytest.raises(PageNotFoundError):
        operations.write_batch(wikis["alpha"], [Operation(op="delete", path="wiki/ghost.md")], "x")


def test_delete_raw_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "raw" / "src.md").write_text("a\n", encoding="utf-8")
    with pytest.raises(RawImmutableError):
        operations.write_batch(wikis["alpha"], [Operation(op="delete", path="raw/src.md")], "x")


def test_delete_log_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    with pytest.raises(ProtectedFileError):
        operations.write_batch(wikis["alpha"], [Operation(op="delete", path="log.md")], "x")


def test_delete_rollback_restores_file(
    wikis: WikiSet,
    git_wiki_roots: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("body\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(alpha), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(alpha), "commit", "-q", "-m", "seed"], check=True)
    version = _version(alpha, "wiki/p.md")

    def boom(*_a: object, **_k: object) -> str:
        raise GitError("commit failed")

    monkeypatch.setattr(operations, "commit_files", boom)
    with pytest.raises(GitError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="delete", path="wiki/p.md", expected_version=version)],
            "x",
        )
    assert (alpha / "wiki" / "p.md").read_text(encoding="utf-8") == "body\n"


# --- rename -----------------------------------------------------------------


def test_rename_succeeds(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "old.md").write_text("body\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(alpha), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(alpha), "commit", "-q", "-m", "seed"], check=True)
    version = _version(alpha, "wiki/old.md")
    result = operations.write_batch(
        wikis["alpha"],
        [
            Operation(
                op="rename",
                path="wiki/old.md",
                new_path="wiki/new.md",
                expected_version=version,
            )
        ],
        "rename",
    )
    assert result["applied"] == [{"op": "rename", "path": "wiki/old.md", "new_path": "wiki/new.md"}]
    assert not (alpha / "wiki" / "old.md").exists()
    assert (alpha / "wiki" / "new.md").read_text(encoding="utf-8") == "body\n"


def test_rename_source_missing(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    with pytest.raises(PageNotFoundError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="rename", path="wiki/ghost.md", new_path="wiki/x.md")],
            "x",
        )


def test_rename_dest_exists(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "a.md").write_text("a\n", encoding="utf-8")
    (alpha / "wiki" / "b.md").write_text("b\n", encoding="utf-8")
    with pytest.raises(RenameDestExistsError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="rename", path="wiki/a.md", new_path="wiki/b.md")],
            "x",
        )


def test_rename_raw_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "raw" / "src.md").write_text("a\n", encoding="utf-8")
    with pytest.raises(RawImmutableError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="rename", path="raw/src.md", new_path="wiki/x.md")],
            "x",
        )


def test_rename_log_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    with pytest.raises(ProtectedFileError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="rename", path="log.md", new_path="wiki/x.md")],
            "x",
        )


def test_rename_then_replace_new_path_same_batch(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    """Rename then replace on the new path works (and needs no version)."""
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "old.md").write_text("placeholder body\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(alpha), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(alpha), "commit", "-q", "-m", "seed"], check=True)
    version = _version(alpha, "wiki/old.md")
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(
                op="rename",
                path="wiki/old.md",
                new_path="wiki/new.md",
                expected_version=version,
            ),
            # new.md was created by the rename in this batch → no version needed.
            Operation(op="replace", path="wiki/new.md", old="placeholder", new="real"),
        ],
        "rename+edit",
    )
    assert not (alpha / "wiki" / "old.md").exists()
    assert (alpha / "wiki" / "new.md").read_text(encoding="utf-8") == "real body\n"


def test_rename_rollback(
    wikis: WikiSet,
    git_wiki_roots: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "old.md").write_text("body\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(alpha), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(alpha), "commit", "-q", "-m", "seed"], check=True)
    version = _version(alpha, "wiki/old.md")
    before = _commit_count(alpha)

    def boom(*_a: object, **_k: object) -> str:
        raise GitError("commit failed")

    monkeypatch.setattr(operations, "commit_files", boom)
    with pytest.raises(GitError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(
                    op="rename",
                    path="wiki/old.md",
                    new_path="wiki/new.md",
                    expected_version=version,
                )
            ],
            "x",
        )
    assert _commit_count(alpha) == before
    assert (alpha / "wiki" / "old.md").read_text(encoding="utf-8") == "body\n"
    assert not (alpha / "wiki" / "new.md").exists()


# --- batch-level guarantees -------------------------------------------------


def test_unknown_op_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    with pytest.raises(UnknownOperationError):
        operations.write_batch(wikis["alpha"], [Operation(op="frobnicate", path="wiki/x.md")], "x")


def test_mixed_batch_atomic_on_bad_op(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    """A bad op in 2nd position → nothing written, nothing committed."""
    alpha = git_wiki_roots["alpha"]
    before = _commit_count(alpha)
    with pytest.raises(CreateExistsError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(op="create", path="wiki/good.md", content="good\n"),
                Operation(op="create", path="index.md", content="dup\n"),
            ],
            "should not apply",
        )
    assert _commit_count(alpha) == before
    assert not (alpha / "wiki" / "good.md").exists()


def test_atomic_on_bad_path(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    before = _commit_count(alpha)
    with pytest.raises(PathEscapeError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(op="create", path="wiki/good.md", content="good\n"),
                Operation(op="create", path="../beta/evil.md", content="evil\n"),
            ],
            "leak",
        )
    assert _commit_count(alpha) == before
    assert not (alpha / "wiki" / "good.md").exists()


def test_only_touches_target_wiki(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    beta = git_wiki_roots["beta"]
    beta_before = _commit_count(beta)
    operations.write_batch(
        wikis["alpha"], [Operation(op="create", path="wiki/x.md", content="x\n")], "m"
    )
    assert _commit_count(beta) == beta_before


def test_multi_op_single_commit(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    before = _commit_count(alpha)
    log_version = _version(alpha, "log.md")
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(op="create", path="wiki/a.md", content="a\n"),
            Operation(op="create", path="raw/b.md", content="b\n"),
            Operation(
                op="replace",
                path="log.md",
                old="<!-- log-end -->",
                new="entry\n\n<!-- log-end -->",
                expected_version=log_version,
            ),
        ],
        "batch",
    )
    assert _commit_count(alpha) == before + 1


def test_empty_batch_raises(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    with pytest.raises(EmptyBatchError):
        operations.write_batch(wikis["alpha"], [], "nothing")


def test_unknown_wiki_raises(wikis: WikiSet) -> None:
    with pytest.raises(UnknownWikiError):
        wikis.get_wiki("zzz")


def test_rollback_on_commit_failure(
    wikis: WikiSet,
    git_wiki_roots: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alpha = git_wiki_roots["alpha"]
    before = _commit_count(alpha)
    index_version = _version(alpha, "index.md")

    def boom(*_a: object, **_k: object) -> str:
        raise GitError("simulated commit failure")

    monkeypatch.setattr(operations, "commit_files", boom)
    with pytest.raises(GitError):
        operations.write_batch(
            wikis["alpha"],
            [
                Operation(op="create", path="wiki/created.md", content="new\n"),
                Operation(
                    op="overwrite",
                    path="index.md",
                    content="# Index modified\n",
                    expected_version=index_version,
                ),
            ],
            "will fail at commit",
        )
    assert _commit_count(alpha) == before
    assert not (alpha / "wiki" / "created.md").exists()
    assert (alpha / "index.md").read_text(encoding="utf-8") == "# Index\n"


# --- zone confinement (A) ---------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [".git/config", "overview.md", "LINT_REPORT.md", "Clippings/x.md", "junk.md"],
)
def test_write_outside_zones_rejected(
    wikis: WikiSet, git_wiki_roots: dict[str, Path], bad_path: str
) -> None:
    """Writes must stay under wiki/, raw/, or the index/log/schema files."""
    alpha = git_wiki_roots["alpha"]
    before = _commit_count(alpha)
    with pytest.raises(WriteZoneError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="create", path=bad_path, content="x\n")],
            "out of zone",
        )
    assert _commit_count(alpha) == before


def test_schema_editable_in_place(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    """schema.md is a mutable root file: overwrite/replace allowed."""
    alpha = git_wiki_roots["alpha"]
    version = _version(alpha, "schema.md")
    operations.write_batch(
        wikis["alpha"],
        [
            Operation(
                op="overwrite",
                path="schema.md",
                content="# Schema v2\n",
                expected_version=version,
            )
        ],
        "edit schema",
    )
    assert (alpha / "schema.md").read_text(encoding="utf-8") == "# Schema v2\n"


# --- structural protection (B) ----------------------------------------------


@pytest.mark.parametrize("protected", ["index.md", "schema.md", "log.md"])
def test_delete_protected_files_rejected(
    wikis: WikiSet, git_wiki_roots: dict[str, Path], protected: str
) -> None:
    alpha = git_wiki_roots["alpha"]
    version = _version(alpha, protected)
    with pytest.raises(ProtectedFileError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="delete", path=protected, expected_version=version)],
            "x",
        )
    assert (alpha / protected).exists()


@pytest.mark.parametrize("protected", ["index.md", "schema.md", "log.md"])
def test_rename_protected_files_rejected(
    wikis: WikiSet, git_wiki_roots: dict[str, Path], protected: str
) -> None:
    alpha = git_wiki_roots["alpha"]
    with pytest.raises(ProtectedFileError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="rename", path=protected, new_path="wiki/moved.md")],
            "x",
        )
    assert (alpha / protected).exists()


# --- CAS on delete / rename (C) ---------------------------------------------


def test_delete_missing_version_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("a\n", encoding="utf-8")
    with pytest.raises(VersionRequiredError):
        operations.write_batch(wikis["alpha"], [Operation(op="delete", path="wiki/p.md")], "x")
    assert (alpha / "wiki" / "p.md").exists()


def test_delete_stale_version_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("a\n", encoding="utf-8")
    with pytest.raises(StaleVersionError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="delete", path="wiki/p.md", expected_version="0000stale")],
            "x",
        )
    assert (alpha / "wiki" / "p.md").exists()


def test_rename_missing_version_rejected(wikis: WikiSet, git_wiki_roots: dict[str, Path]) -> None:
    alpha = git_wiki_roots["alpha"]
    (alpha / "wiki" / "p.md").write_text("a\n", encoding="utf-8")
    with pytest.raises(VersionRequiredError):
        operations.write_batch(
            wikis["alpha"],
            [Operation(op="rename", path="wiki/p.md", new_path="wiki/q.md")],
            "x",
        )


def test_wiki_yaml_is_outside_the_write_zones(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    """The model must never be able to rewrite the rules that bind it."""
    root = git_wiki_roots["alpha"]
    (root / "wiki.yaml").write_text("mindyard: 1\n", encoding="utf-8")
    for op in (
        Operation(op="create", path="wiki.yaml", content="x"),
        Operation(op="overwrite", path="wiki.yaml", content="x", expected_version="0"),
        Operation(op="delete", path="wiki.yaml", expected_version="0"),
    ):
        with pytest.raises(ConfigLockedError):
            operations.write_batch(wikis["alpha"], [op], "tamper", config_check=_accept)
    assert (root / "wiki.yaml").read_text(encoding="utf-8") == "mindyard: 1\n"


def _accept(current: str, proposed: str) -> None:
    """A validator that accepts anything: the core's own rules are under test."""


_BLANK = "# mindyard:bootstrap\nmindyard: 1\nlabel: Alpha\n"


def _blank_vault(root: Path) -> str:
    (root / "wiki.yaml").write_text(_BLANK, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "wiki.yaml"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "blank"], check=True)
    return content_version(_BLANK)


def test_a_blank_config_can_be_defined_once(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    root = git_wiki_roots["alpha"]
    version = _blank_vault(root)
    defined = "mindyard: 1\nlabel: Alpha\ndescription: Books\n"
    op = Operation(op="overwrite", path="wiki.yaml", content=defined, expected_version=version)
    operations.write_batch(wikis["alpha"], [op], "define", config_check=_accept)
    assert (root / "wiki.yaml").read_text(encoding="utf-8") == defined
    again = Operation(
        op="overwrite", path="wiki.yaml", content=_BLANK, expected_version=content_version(defined)
    )
    with pytest.raises(ConfigLockedError):  # the marker is gone: locked for good
        operations.write_batch(wikis["alpha"], [again], "redefine", config_check=_accept)


def test_a_blank_config_stays_locked_without_a_validator(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    root = git_wiki_roots["alpha"]
    version = _blank_vault(root)
    op = Operation(op="overwrite", path="wiki.yaml", content="label: x\n", expected_version=version)
    with pytest.raises(ConfigLockedError):
        operations.write_batch(wikis["alpha"], [op], "define")
    assert (root / "wiki.yaml").read_text(encoding="utf-8") == _BLANK


@pytest.mark.parametrize("op", ["create", "delete", "rename"])
def test_a_blank_config_still_refuses_other_operations(
    wikis: WikiSet, git_wiki_roots: dict[str, Path], op: str
) -> None:
    root = git_wiki_roots["alpha"]
    version = _blank_vault(root)
    entry = {
        "create": Operation(op="create", path="wiki.yaml", content="x"),
        "delete": Operation(op="delete", path="wiki.yaml", expected_version=version),
        "rename": Operation(
            op="rename", path="wiki.yaml", new_path="wiki/c.md", expected_version=version
        ),
    }[op]
    with pytest.raises(ConfigLockedError):
        operations.write_batch(wikis["alpha"], [entry], "tamper", config_check=_accept)
    assert (root / "wiki.yaml").read_text(encoding="utf-8") == _BLANK


def test_a_definition_must_drop_the_marker_and_pass_the_check(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    root = git_wiki_roots["alpha"]
    version = _blank_vault(root)
    keep_marker = Operation(
        op="overwrite",
        path="wiki.yaml",
        content=_BLANK + "description: x\n",
        expected_version=version,
    )
    with pytest.raises(ConfigRejectedError, match="one-time"):
        operations.write_batch(wikis["alpha"], [keep_marker], "x", config_check=_accept)

    def refuse(current: str, proposed: str) -> None:
        raise ConfigRejectedError("not valid")

    page = Operation(op="create", path="wiki/new.md", content="x")
    define = Operation(op="overwrite", path="wiki.yaml", content="x\n", expected_version=version)
    with pytest.raises(ConfigRejectedError, match="not valid"):
        operations.write_batch(wikis["alpha"], [page, define], "x", config_check=refuse)
    assert (root / "wiki.yaml").read_text(encoding="utf-8") == _BLANK
    assert not (root / "wiki" / "new.md").exists()  # the whole batch is refused


def test_concurrent_batches_on_one_wiki_are_serialised(
    wikis: WikiSet, git_wiki_roots: dict[str, Path]
) -> None:
    """Parallel batches each land in their own commit, none is lost."""
    from concurrent.futures import ThreadPoolExecutor

    root = git_wiki_roots["alpha"]
    before = _commit_count(root)

    def create(i: int) -> str:
        edits = [Operation(op="create", path=f"wiki/p{i}.md", content=f"{i}\n")]
        return operations.write_batch(wikis["alpha"], edits, f"page {i}")["commit"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        commits = list(pool.map(create, range(16)))

    assert len(set(commits)) == 16
    assert _commit_count(root) == before + 16


def test_a_git_call_that_hangs_fails_the_batch_and_rolls_back(
    wikis: WikiSet, git_wiki_roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A git that waits (a signing prompt, a locked file) must not hang the server."""
    root = git_wiki_roots["alpha"]
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nsleep 10\n", encoding="utf-8")
    hook.chmod(0o755)
    monkeypatch.setattr("mindyard.core.git.GIT_TIMEOUT_SECONDS", 1)
    with pytest.raises(GitError, match="did not finish"):
        operations.write_batch(
            wikis["alpha"], [Operation(op="create", path="wiki/slow.md", content="x")], "slow"
        )
    assert not (root / "wiki" / "slow.md").exists()
