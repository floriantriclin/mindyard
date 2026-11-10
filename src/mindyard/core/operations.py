# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure operation logic behind the MCP tools.

Each function takes an already-resolved :class:`WikiConfig` plus the tool
arguments, performs the work, and either returns plain data or raises a domain
error from :mod:`mindyard.core.errors`. Resolving *which* wiki (and whose) is the
caller's job: the core only ever sees one wiki at a time, which keeps it directly
unit-testable without a FastMCP client or an identity.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import NotRequired

# typing_extensions.TypedDict (not typing.TypedDict) so Pydantic/FastMCP can build
# a schema for the write_batch ``edits`` param on Python < 3.12 as well as 3.12+.
from typing_extensions import TypedDict

from .config import WikiConfig
from .errors import (
    CreateExistsError,
    EmptyBatchError,
    InvalidFileError,
    InvalidScopeError,
    OverwriteMissingError,
    PageNotFoundError,
    ProtectedFileError,
    RawImmutableError,
    RenameDestExistsError,
    ReplaceAmbiguousError,
    ReplaceNotFoundError,
    ReplaceTargetMissingError,
    StaleVersionError,
    UnknownOperationError,
    VersionRequiredError,
    WriteZoneError,
)
from .git import commit_files, head_sha, rollback
from .paths import resolve_within
from .render import escape_table_pipes, strip_wikilinks
from .search import SearchHit, search

_ALLOWED_SCOPES = ("wiki", "raw", "all")
_ALLOWED_OPS = ("create", "overwrite", "replace", "delete", "rename")

# Below this many lines, ``read_page`` returns the whole file even with no
# explicit ``limit``; above it, an unbounded read auto-paginates to the first
# page and flags ``truncated`` so the client knows to request more.
AUTO_PAGE_LIMIT = 400

# Length of the hex content-version token (a sha256 prefix). Stable across a
# read/replace round trip because it is always computed over the raw on-disk
# bytes, never the rendered form (see ``content_version``).
_VERSION_LEN = 16


def content_version(text: str) -> str:
    """Return a short, stable content version token for ``text``.

    A 16-hex-char sha256 prefix over the raw bytes. Used as the optimistic
    concurrency token: ``read_page`` returns it and ``replace``/``overwrite``
    must carry it back so a stale read is rejected before any write.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_VERSION_LEN]


def _scope_subdirs(cfg: WikiConfig, scope: str) -> list[str]:
    """Map a ``scope`` to the wiki subdirectories it covers."""
    if scope == "wiki":
        return [cfg.wiki_dir]
    if scope == "raw":
        return [cfg.raw_dir]
    if scope == "all":
        return [cfg.wiki_dir, cfg.raw_dir]
    raise InvalidScopeError(scope, list(_ALLOWED_SCOPES))


# --- Read tools -------------------------------------------------------------


class PageView(TypedDict):
    """Structured result of ``read_page``.

    ``content`` is verbatim (no ``cat -n`` prefix) so a ``replace`` op's ``old``
    stays byte-for-byte. ``version`` is the optimistic-concurrency token over the
    full raw bytes. The line-range fields describe the returned window.
    """

    content: str
    version: str
    total_lines: int
    start_line: int
    end_line: int
    truncated: bool


def read_page(
    cfg: WikiConfig,
    path: str,
    raw: bool = False,
    offset: int = 1,
    limit: int | None = None,
) -> PageView:
    """Read a file in the target wiki, confined to its root, as a ``PageView``.

    By default the content is rendered for display: Obsidian wikilinks are
    stripped (``[[a|b]]`` -> ``b``, ``[[a]]`` -> removed) so the LLM never shows
    a wikilink. Pass ``raw=True`` to get the verbatim bytes, required before
    editing a page so ``write_batch`` can preserve ``[[...]]`` on disk.

    ``offset`` is 1-based; ``limit`` caps the number of lines returned. Wikilink
    stripping is intra-line (never drops a line), so line numbers are identical
    in raw and rendered modes. ``version`` is always computed over the raw bytes,
    so it is identical whether you read raw or rendered, and is the token to pass
    back as ``expected_version`` on a later ``replace``/``overwrite``.
    """
    resolved = resolve_within(cfg.root, path)
    if not resolved.is_file():
        raise PageNotFoundError(path)

    raw_text = resolved.read_text(encoding="utf-8")
    version = content_version(raw_text)
    full = raw_text if raw else strip_wikilinks(raw_text)

    lines = full.splitlines(keepends=True)
    total = len(lines)

    start_idx = max(offset - 1, 0)
    if limit is None:
        eff_limit = AUTO_PAGE_LIMIT if total > AUTO_PAGE_LIMIT else None
    else:
        eff_limit = max(limit, 0)
    end_idx = total if eff_limit is None else min(start_idx + eff_limit, total)

    chunk = lines[start_idx:end_idx]
    return PageView(
        content="".join(chunk),
        version=version,
        total_lines=total,
        start_line=start_idx + 1,
        end_line=start_idx + len(chunk),
        truncated=end_idx < total,
    )


class PageList(TypedDict):
    """Structured result of ``list_pages`` (capped, with the true total)."""

    pages: list[str]
    truncated: bool
    total: int


def list_pages(
    cfg: WikiConfig,
    scope: str = "wiki",
    prefix: str = "",
    limit: int = 200,
) -> PageList:
    """List ``*.md`` files in a zone, as paths relative to the wiki root.

    Results are sorted and capped at ``limit``; ``total`` is the true count and
    ``truncated`` is true when the list was cut.
    """
    subdirs = _scope_subdirs(cfg, scope)
    pages: list[str] = []
    for subdir in subdirs:
        base = cfg.root / subdir
        if not base.exists():
            continue
        for md in base.rglob("*.md"):
            rel = md.relative_to(cfg.root).as_posix()
            if rel.startswith(prefix):
                pages.append(rel)
    pages.sort()
    total = len(pages)
    capped = pages[:limit] if limit >= 0 else pages
    return PageList(pages=capped, truncated=total > len(capped), total=total)


def search_wiki(
    cfg: WikiConfig,
    query: str,
    scope: str = "wiki",
    max_results: int = 30,
    regex: bool = False,
) -> list[SearchHit]:
    """Full-text, case-insensitive search scoped to the target wiki.

    ``regex=False`` (default) matches ``query`` literally; ``regex=True`` treats
    it as a regular expression (raises ``InvalidRegexError`` if invalid).
    """
    subdirs = _scope_subdirs(cfg, scope)
    return search(cfg.root, subdirs, query, max_results, regex)


def get_lint_report(cfg: WikiConfig) -> str:
    """Return the wiki's lint report, or a message if none exists yet."""
    report = cfg.root / cfg.lint_report_file
    if not report.is_file():
        return f"No lint report available for wiki '{cfg.id}'."
    return report.read_text(encoding="utf-8")


# --- write_batch: typed edit operations -------------------------------------


class Operation(TypedDict):
    """A single edit operation in a ``write_batch``.

    ``op`` selects the verb; the other fields are validated per op (manual
    ``NotRequired`` checks, like the old ``_validate_edits``, rather than a
    discriminated union, a flatter JSON schema is more predictable for clients):

    - ``create``    : ``path``, ``content``
    - ``overwrite`` : ``path``, ``content``, ``expected_version``
    - ``replace``   : ``path``, ``old``, ``new``, ``expected_version`` (``replace_all``)
    - ``delete``    : ``path``
    - ``rename``    : ``path``, ``new_path``

    ``expected_version`` is the optimistic-concurrency token from ``read_page``;
    it is required on ``replace``/``overwrite`` of an existing file and ignored
    when the target was created earlier in the same batch.
    """

    op: str
    path: NotRequired[str]
    content: NotRequired[str]
    old: NotRequired[str]
    new: NotRequired[str]
    new_path: NotRequired[str]
    replace_all: NotRequired[bool]
    expected_version: NotRequired[str]


class _Deleted:
    """Sentinel for a path removed within the simulated batch state."""


_DELETED = _Deleted()


@dataclass
class _Plan:
    """Compiled result of simulating a batch, ready to execute against disk."""

    writes: list[tuple[Path, str]] = field(default_factory=list)
    deletes: list[Path] = field(default_factory=list)
    created_rel: list[str] = field(default_factory=list)
    touched_rel: list[str] = field(default_factory=list)
    applied: list[dict[str, str]] = field(default_factory=list)
    normalized: list[dict[str, object]] = field(default_factory=list)


class WriteResult(TypedDict):
    commit: str
    applied: list[dict[str, str]]
    # Deterministic rewrites applied on write (currently: table-cell pipes
    # escaped in aliased wikilinks). Empty when nothing had to be fixed.
    normalized: NotRequired[list[dict[str, object]]]


def _require(entry: Operation, field_name: str, op: str) -> str:
    """Return a required string field of ``entry`` or raise ``InvalidFileError``."""
    value = entry.get(field_name)
    if value is None:
        raise InvalidFileError(f"op '{op}' requires '{field_name}'")
    if not isinstance(value, str):
        raise InvalidFileError(f"op '{op}' field '{field_name}' must be a string")
    return value


def _plan_ops(cfg: WikiConfig, edits: list[Operation]) -> _Plan:
    """Simulate ``edits`` against the worktree, validating before any write.

    Maintains ``state`` (a path -> content | _DELETED overlay on disk) and applies
    each op in order, so chained edits to the same path see prior results for
    free. Raises on the first problem, so a single bad op means nothing is
    written and nothing is committed. Reads disk but never writes it, so the
    content-version checks always see the original on-disk bytes.
    """
    root = cfg.root
    wiki_root = (root / cfg.wiki_dir).resolve()
    raw_root = (root / cfg.raw_dir).resolve()
    index_path = (root / cfg.index_file).resolve()
    log_path = (root / cfg.log_file).resolve()
    schema_path = (root / cfg.schema_file).resolve()

    # Writes are confined to the content zones plus these mutable root files;
    # everything else under the root (.git/, generated reports, ad-hoc files) is
    # rejected even though it resolves inside the wiki.
    mutable_root_files = {index_path, log_path, schema_path}
    # Structural files: editable in place (overwrite/replace) but never removed
    # or renamed, so the wiki keeps its load-bearing pieces.
    protected: dict[Path, str] = {
        log_path: "the log is append-only (add entries by replacing its sentinel)",
        index_path: "the index is curated (edit it in place, never delete or rename)",
        schema_path: "the schema is structural (edit it in place, never delete or rename)",
    }

    state: dict[Path, str | _Deleted] = {}
    created: set[Path] = set()

    def writable(user_path: str) -> Path:
        """Resolve under root and confine to the writable zones."""
        p = resolve_within(root, user_path)
        if p.is_relative_to(wiki_root) or p.is_relative_to(raw_root) or p in mutable_root_files:
            return p
        raise WriteZoneError(user_path)

    def is_raw(p: Path) -> bool:
        return p.is_relative_to(raw_root)

    def current(p: Path) -> str | _Deleted | None:
        """Current simulated content: state overlay, else disk, else absent."""
        if p in state:
            return state[p]
        if p.is_file():
            return p.read_text(encoding="utf-8")
        return None

    def check_version(entry: Operation, p: Path, user_path: str) -> None:
        """Optimistic-concurrency check against the original on-disk bytes.

        Skipped when the target was created earlier in this batch (no disk base).
        """
        if p in created:
            return
        expected = entry.get("expected_version")
        if not expected:
            raise VersionRequiredError(user_path)
        actual = content_version(p.read_text(encoding="utf-8"))
        if expected != actual:
            raise StaleVersionError(user_path, expected, actual)

    applied: list[dict[str, str]] = []
    normalized: list[dict[str, object]] = []

    def put(p: Path, user_path: str, content: str) -> None:
        """Stage simulated content, normalising Markdown outside ``raw/``.

        ``raw/`` holds verbatim sources and is never touched. Everywhere else,
        an aliased wikilink in a table cell gets its pipe escaped: a bare ``|``
        would be read as a column separator and break both the table and the
        link. The rewrite is deterministic and semantically inert, so it is
        applied rather than rejected, an atomic batch carrying a whole page
        should not have to be regenerated over a missing backslash. What was
        changed is reported back in the result.
        """
        if not is_raw(p):
            content, n = escape_table_pipes(content)
            if n:
                normalized.append({"path": user_path, "table_pipes": n})
        state[p] = content

    for entry in edits:
        op = entry.get("op")
        if op not in _ALLOWED_OPS:
            raise UnknownOperationError(op, list(_ALLOWED_OPS))

        if op == "create":
            user_path = _require(entry, "path", op)
            content = _require(entry, "content", op)
            p = writable(user_path)
            cur = current(p)
            if cur is not None and not isinstance(cur, _Deleted):
                raise CreateExistsError(user_path)
            put(p, user_path, content)
            created.add(p)
            applied.append({"op": op, "path": user_path})

        elif op == "overwrite":
            user_path = _require(entry, "path", op)
            content = _require(entry, "content", op)
            p = writable(user_path)
            if is_raw(p):
                raise RawImmutableError(user_path)
            cur = current(p)
            if cur is None or isinstance(cur, _Deleted):
                raise OverwriteMissingError(user_path)
            check_version(entry, p, user_path)
            put(p, user_path, content)
            applied.append({"op": op, "path": user_path})

        elif op == "replace":
            user_path = _require(entry, "path", op)
            old = _require(entry, "old", op)
            new = _require(entry, "new", op)
            replace_all = bool(entry.get("replace_all", False))
            p = writable(user_path)
            if is_raw(p):
                raise RawImmutableError(user_path)
            cur = current(p)
            if cur is None or isinstance(cur, _Deleted):
                raise ReplaceTargetMissingError(user_path)
            check_version(entry, p, user_path)
            count = cur.count(old)
            if count == 0:
                raise ReplaceNotFoundError(user_path)
            if count > 1 and not replace_all:
                raise ReplaceAmbiguousError(user_path, count)
            put(p, user_path, cur.replace(old, new) if replace_all else cur.replace(old, new, 1))
            applied.append({"op": op, "path": user_path})

        elif op == "delete":
            user_path = _require(entry, "path", op)
            p = writable(user_path)
            if is_raw(p):
                raise RawImmutableError(user_path)
            if p in protected:
                raise ProtectedFileError(user_path, protected[p])
            cur = current(p)
            if cur is None or isinstance(cur, _Deleted):
                raise PageNotFoundError(user_path)
            check_version(entry, p, user_path)
            state[p] = _DELETED
            created.discard(p)
            applied.append({"op": op, "path": user_path})

        elif op == "rename":
            user_path = _require(entry, "path", op)
            new_path = _require(entry, "new_path", op)
            src = writable(user_path)
            dst = writable(new_path)
            if is_raw(src) or is_raw(dst):
                raise RawImmutableError(user_path if is_raw(src) else new_path)
            if src in protected:
                raise ProtectedFileError(user_path, protected[src])
            cur = current(src)
            if cur is None or isinstance(cur, _Deleted):
                raise PageNotFoundError(user_path)
            dst_cur = current(dst)
            if dst_cur is not None and not isinstance(dst_cur, _Deleted):
                raise RenameDestExistsError(user_path, new_path)
            check_version(entry, src, user_path)
            state[src] = _DELETED
            created.discard(src)
            state[dst] = cur
            created.add(dst)
            applied.append({"op": op, "path": user_path, "new_path": new_path})

    return _compile_plan(root, state, applied, normalized)


def _compile_plan(
    root: Path,
    state: dict[Path, str | _Deleted],
    applied: list[dict[str, str]],
    normalized: list[dict[str, object]] | None = None,
) -> _Plan:
    """Turn the simulated ``state`` into concrete writes/deletes for execution."""
    plan = _Plan(applied=applied, normalized=normalized or [])
    for p, value in state.items():
        rel = p.relative_to(root).as_posix()
        on_disk = p.is_file()
        if isinstance(value, _Deleted):
            # A path created and then deleted within the same batch never hit
            # disk, so there is nothing to stage for it.
            if on_disk:
                plan.deletes.append(p)
                plan.touched_rel.append(rel)
        else:
            plan.writes.append((p, value))
            plan.touched_rel.append(rel)
            if not on_disk:
                plan.created_rel.append(rel)
    return plan


_WRITE_LOCKS: dict[Path, threading.Lock] = {}
_WRITE_LOCKS_GUARD = threading.Lock()


def _write_lock(root: Path) -> threading.Lock:
    """One lock per wiki root, so batches on the same wiki never interleave.

    The rollback relies on a clean worktree at the start of each batch; two
    batches planned against the same HEAD and written concurrently would break
    both the CAS checks and that assumption. Different wikis stay parallel.
    """
    key = root.resolve()
    with _WRITE_LOCKS_GUARD:
        return _WRITE_LOCKS.setdefault(key, threading.Lock())


def write_batch(
    cfg: WikiConfig, edits: list[Operation], message: str, author: str | None = None
) -> WriteResult:
    """Transactionally apply ``edits`` to the target wiki in one commit.

    Order: simulate all ops (confinement + raw immutability + version checks),
    snapshot HEAD, write/delete, commit. Any failure during write/commit triggers
    a rollback (reset to HEAD + removal of created files), so the batch is
    all-or-nothing. Returns ``{commit, applied}``, plus ``normalized`` when the
    server had to fix table-cell pipes on the way in (see ``escape_table_pipes``).
    ``author`` (``Name <email>``) attributes the commit to the caller; the
    committer stays the repository's identity.
    """
    if not edits:
        raise EmptyBatchError()

    with _write_lock(cfg.root):
        plan = _plan_ops(cfg, edits)
        start_sha = head_sha(cfg.root)

        try:
            for resolved, content in plan.writes:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                resolved.write_text(content, encoding="utf-8")
            for resolved in plan.deletes:
                if resolved.exists():
                    resolved.unlink()
            commit = commit_files(cfg.root, plan.touched_rel, message, author)
        except Exception:
            rollback(cfg.root, start_sha, plan.created_rel)
            raise

    result = WriteResult(commit=commit, applied=plan.applied)
    if plan.normalized:
        result["normalized"] = plan.normalized
    return result
