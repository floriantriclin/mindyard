# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lint checks: pure functions over an in-memory snapshot of one wiki.

Generic checks apply to every wiki. Declared checks apply only when the wiki's
``wiki.yaml`` declares the rule (entity kinds, closed status lists, statuses
implied by dates): a rule nobody declared never fires.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from fnmatch import fnmatch
from typing import Any

from mindyard.schema.manifest import DateDerivedStatus, WikiManifest

from .markdown import (
    UNESCAPED_PIPE_RE,
    WIKILINK_RE,
    FrontmatterError,
    as_date,
    file_stem_key,
    frontmatter,
    is_file_ref,
    link_key,
    link_targets,
)


@dataclass(frozen=True)
class Rule:
    title: str
    counted: bool  # an error, counted in the total; otherwise a notice


RULES: dict[str, Rule] = {
    "broken_link": Rule("Broken file links", True),
    "orphan": Rule("Orphan pages", True),
    "missing_frontmatter": Rule("Pages without frontmatter", True),
    "invalid_frontmatter": Rule("Unreadable frontmatter", True),
    "unreferenced_raw": Rule("Raw files cited by no page", True),
    "table_pipe": Rule("Unescaped pipes in table wikilinks", True),
    "missing_field": Rule("Missing required fields", True),
    "invalid_status": Rule("Status outside the declared list", True),
    "unresolved_link": Rule("Links to pages not written yet", False),
    "long_index_entry": Rule("Over-long index entries", False),
    "status_date_conflict": Rule("Status contradicted by dates", False),
}


@dataclass(frozen=True)
class Finding:
    rule: str
    path: str
    detail: str = ""


@dataclass(frozen=True)
class Page:
    rel: str
    text: str

    @property
    def key(self) -> str:
        return link_key(self.rel)


@dataclass
class Snapshot:
    pages: list[Page]  # wiki-zone pages, plus the index
    raw_files: list[str]
    index_rel: str
    extra_targets: set[str] = field(default_factory=set)  # root files that exist


@dataclass
class Findings:
    items: list[Finding]
    pages_scanned: int
    raw_scanned: int

    @property
    def total(self) -> int:
        return sum(1 for f in self.items if RULES[f.rule].counted)

    def by_rule(self, rule: str) -> list[Finding]:
        return [f for f in self.items if f.rule == rule]


# --- generic -----------------------------------------------------------------


def _known_targets(snap: Snapshot) -> set[str]:
    known = {page.key for page in snap.pages}
    known |= {file_stem_key(rel) for rel in snap.raw_files}
    known |= {rel.rsplit("/", 1)[-1].lower() for rel in snap.raw_files}
    return known | snap.extra_targets


def check_links(snap: Snapshot) -> Iterator[Finding]:
    known = _known_targets(snap)
    for page in snap.pages:
        for target in link_targets(page.text):
            if link_key(target) not in known:
                rule = "broken_link" if is_file_ref(target) else "unresolved_link"
                yield Finding(rule, page.rel, target)


def check_orphans(snap: Snapshot, exempt: list[str]) -> Iterator[Finding]:
    referenced = {
        link_key(t)
        for page in snap.pages
        for t in link_targets(page.text)
        if link_key(t) != page.key
    }
    for page in snap.pages:
        if page.rel == snap.index_rel or any(fnmatch(page.rel, g) for g in exempt):
            continue
        if page.key not in referenced:
            yield Finding("orphan", page.rel)


def check_unreferenced_raw(snap: Snapshot) -> Iterator[Finding]:
    corpus = "\n".join(page.text for page in snap.pages)
    linked = {link_key(t) for page in snap.pages for t in link_targets(page.text)}
    for rel in snap.raw_files:
        if file_stem_key(rel) in linked or rel in corpus or rel.rsplit("/", 1)[-1] in corpus:
            continue
        yield Finding("unreferenced_raw", rel)


def check_table_pipes(snap: Snapshot) -> Iterator[Finding]:
    for page in snap.pages:
        for line in page.text.splitlines():
            if line.lstrip().startswith("|"):
                for match in WIKILINK_RE.finditer(line):
                    if UNESCAPED_PIPE_RE.search(match.group(1)):
                        yield Finding("table_pipe", page.rel, match.group(0))


def check_index_entries(snap: Snapshot, max_chars: int | None) -> Iterator[Finding]:
    """An index line that grew into a summary of the page it should point to."""
    if max_chars is None:
        return
    for page in snap.pages:
        if page.rel != snap.index_rel:
            continue
        for line in page.text.splitlines():
            if line.lstrip().startswith("- [[") and len(line) > max_chars:
                match = WIKILINK_RE.search(line)
                target = match.group(1).split("|", 1)[0].strip() if match else line[:60]
                yield Finding("long_index_entry", page.rel, f"{target} ({len(line)} chars)")


# --- frontmatter, generic and declared ---------------------------------------


def derive_status(rule: DateDerivedStatus, start: date, end: date | None, today: date) -> str:
    """The status dates imply as of ``today``; no end date means a single day."""
    if (end or start) < today:
        return rule.past
    return rule.upcoming if start > today else rule.ongoing


def _check_entity(
    page: Page, fm: dict[str, Any], manifest: WikiManifest, today: date
) -> Iterator[Finding]:
    kind_name = fm.get("entity_kind")
    if not isinstance(kind_name, str) or kind_name not in manifest.entities:
        return
    kind = manifest.entities[kind_name]
    missing = [name for name in kind.required if fm.get(name) in (None, "", [])]
    if missing:
        yield Finding("missing_field", page.rel, f"{kind_name}: {', '.join(missing)}")
    status = fm.get("status")
    if kind.status is None or status in (None, ""):
        return
    if status not in kind.status:
        yield Finding("invalid_status", page.rel, f"{kind_name}: {status!r}")
        return
    rule = kind.status_from_dates
    if rule is None:
        return
    start = as_date(fm.get(rule.start))
    if start is None:
        yield Finding("status_date_conflict", page.rel, f"no valid '{rule.start}' to check")
        return
    end = as_date(fm.get(rule.end)) if rule.end else None
    derived = derive_status(rule, start, end, today)
    if derived != status:
        yield Finding("status_date_conflict", page.rel, f"{status!r}, dates imply {derived!r}")


def check_frontmatter(snap: Snapshot, manifest: WikiManifest, today: date) -> Iterator[Finding]:
    for page in snap.pages:
        if page.rel == snap.index_rel:
            continue
        try:
            fm = frontmatter(page.text)
        except FrontmatterError as exc:
            yield Finding("invalid_frontmatter", page.rel, str(exc))
            continue
        if fm is None:
            yield Finding("missing_frontmatter", page.rel)
            continue
        yield from _check_entity(page, fm, manifest, today)


def run_checks(snap: Snapshot, manifest: WikiManifest, today: date) -> Findings:
    items = [
        *check_links(snap),
        *check_orphans(snap, manifest.lint.orphans.exempt),
        *check_frontmatter(snap, manifest, today),
        *check_unreferenced_raw(snap),
        *check_table_pipes(snap),
        *check_index_entries(snap, manifest.lint.index_entry_max_chars),
    ]
    return Findings(items, len(snap.pages), len(snap.raw_files))
