# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolved, immutable configuration of one wiki, as the core sees it.

The core never parses configuration files: ``mindyard.schema`` turns a vault's
``wiki.yaml`` into a :class:`WikiConfig`, and the tenancy layer hands the core a
:class:`WikiSet` already scoped to the caller. Nothing in ``mindyard.core`` knows
where a wiki came from or whom it belongs to.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from .errors import UnknownWikiError

CONFIG_FILE = "wiki.yaml"


@dataclass(frozen=True)
class WikiConfig:
    """Layout of a single wiki vault.

    ``index_file``, ``log_file`` and ``schema_file`` are the only root files the
    write path may touch. ``config_file`` (``wiki.yaml``) is deliberately not one
    of them: the model must not be able to rewrite the rules that bind it.
    """

    id: str
    root: Path
    label: str
    description: str = ""
    wiki_dir: str = "wiki"
    raw_dir: str = "raw"
    index_file: str = "index.md"
    log_file: str = "log.md"
    schema_file: str = "schema.md"
    lint_report_file: str = "LINT_REPORT.md"
    log_sentinel: str = "<!-- log-end -->"


class WikiSet(Mapping[str, WikiConfig]):
    """The wikis visible to one caller, keyed by id.

    :meth:`get_wiki` is the single validation gate for a ``wiki`` argument. The
    error lists only the ids of this set, so it never reveals another tenant's.
    """

    def __init__(self, wikis: Mapping[str, WikiConfig]) -> None:
        self._wikis = dict(wikis)

    def __getitem__(self, key: str) -> WikiConfig:
        return self._wikis[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._wikis)

    def __len__(self) -> int:
        return len(self._wikis)

    def get_wiki(self, wiki_id: str) -> WikiConfig:
        try:
            return self._wikis[wiki_id]
        except KeyError:
            raise UnknownWikiError(wiki_id, list(self._wikis)) from None
