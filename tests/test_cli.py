# SPDX-License-Identifier: AGPL-3.0-or-later
"""Command line: init, lint, token."""

from __future__ import annotations

from pathlib import Path

import pytest

from mindyard.auth import TokenStore
from mindyard.auth.tokens import digest
from mindyard.cli import main
from mindyard.schema import discover_wikis


@pytest.mark.parametrize("flag", [[], ["--demo"]])
def test_init_creates_a_valid_committed_vault(tmp_path: Path, flag: list[str]) -> None:
    target = tmp_path / "vaults" / "my-notes"
    assert main(["init", str(target), *flag]) == 0
    wikis, problems = discover_wikis(tmp_path / "vaults")
    assert problems == []
    assert wikis["my-notes"].config.label == ("My notes")
    assert main(["lint", str(target)]) == 0
    assert "$" not in (target / "log.md").read_text(encoding="utf-8")


def test_init_refuses_a_non_empty_directory(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "keep.txt").write_text("mine", encoding="utf-8")
    assert main(["init", str(tmp_path / "x")]) == 2
    assert (tmp_path / "x" / "keep.txt").read_text(encoding="utf-8") == "mine"


def test_lint_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "notes"
    main(["init", str(target)])
    (target / "wiki" / "loose.md").write_text("no frontmatter\n", encoding="utf-8")
    assert main(["lint", str(target)]) == 1
    assert "2 issue(s)" in capsys.readouterr().out  # missing frontmatter, orphan
    assert main(["lint", str(tmp_path)]) == 2


def test_token_new_prints_the_token_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["token", "new", "laptop", "--data-root", str(tmp_path)]) == 0
    token = capsys.readouterr().out.strip()
    assert TokenStore.load(tmp_path / "tokens.yaml").by_digest == {digest(token): "laptop"}
    assert main(["token", "new", "laptop", "--data-root", str(tmp_path)]) == 2
