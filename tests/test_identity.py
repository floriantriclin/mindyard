# SPDX-License-Identifier: AGPL-3.0-or-later
"""Commit authorship derived from the caller."""

from __future__ import annotations

import pytest

from mindyard.identity import Identity, git_author

ISS = "https://issuer.example"


@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        (
            Identity(ISS, "s", "ada@example.org", True, {"name": "Ada North"}),
            "Ada North <ada@example.org>",
        ),
        (Identity(ISS, "s", "ada@example.org", True), "ada <ada@example.org>"),
        (Identity(ISS, "s", "ada@example.org", False, {"name": "Ada"}), None),
        (Identity(ISS, "s"), None),
        (None, None),
        (
            Identity(ISS, "s", "ada@example.org", True, {"name": "Eve <x@y>\nCommitter: z"}),
            "Eve x@yCommitter: z <ada@example.org>",
        ),
    ],
)
def test_git_author(identity: Identity | None, expected: str | None) -> None:
    assert git_author(identity) == expected
