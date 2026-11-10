# SPDX-License-Identifier: AGPL-3.0-or-later
"""Domain exceptions for the mindyard.

Each error carries a user-facing message safe to surface through MCP. None of
these leak absolute server paths or stack traces; tool wrappers convert them to
``ToolError`` with the message verbatim.
"""

from __future__ import annotations


class MindyardError(Exception):
    """Base class for all mindyard domain errors."""


class UnknownWikiError(MindyardError):
    """Raised when a ``wiki`` id is not among the caller's wikis."""

    def __init__(self, wiki_id: str, known: list[str]) -> None:
        self.wiki_id = wiki_id
        self.known = known
        known_str = ", ".join(sorted(known)) if known else "(none)"
        super().__init__(f"Unknown wiki '{wiki_id}'. Known wikis: {known_str}.")


class PathEscapeError(MindyardError):
    """Raised when a user-supplied path resolves outside its wiki root.

    The message only ever names the offending *relative* path, never the
    resolved absolute path, to avoid leaking server layout.
    """

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(f"Path '{user_path}' is outside the wiki root.")


class RawImmutableError(MindyardError):
    """Raised when ``write_batch`` would mutate a ``raw/`` file.

    ``raw/`` is create-only: a raw file may be written once, whole. Overwrite,
    replace, delete and rename are all refused. Whole-file creation of a *new*
    raw path is the only allowed raw write.
    """

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(
            f"Cannot modify '{user_path}': files under raw/ are create-only "
            "(overwrite/replace/delete/rename refused)."
        )


class PageNotFoundError(MindyardError):
    """Raised when a requested page does not exist in the wiki."""

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(f"Page '{user_path}' not found.")


class InvalidScopeError(MindyardError):
    """Raised when a ``scope`` argument is not one of the allowed zones."""

    def __init__(self, scope: str, allowed: list[str]) -> None:
        self.scope = scope
        self.allowed = allowed
        super().__init__(f"Invalid scope '{scope}'. Allowed: {', '.join(allowed)}.")


class EmptyBatchError(MindyardError):
    """Raised when ``write_batch`` is called with no operations."""

    def __init__(self) -> None:
        super().__init__("write_batch requires at least one operation.")


class InvalidFileError(MindyardError):
    """Raised when an operation entry is missing a required field."""

    def __init__(self, detail: str) -> None:
        super().__init__(f"Invalid operation entry: {detail}.")


class UnknownOperationError(MindyardError):
    """Raised when an operation's ``op`` is not a known edit verb."""

    def __init__(self, op: object, allowed: list[str]) -> None:
        self.op = op
        self.allowed = allowed
        super().__init__(f"Unknown operation '{op}'. Allowed: {', '.join(allowed)}.")


class CreateExistsError(MindyardError):
    """Raised when ``create`` targets a path that already exists."""

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(
            f"Cannot create '{user_path}': it already exists "
            "(use 'overwrite' or 'replace' to modify an existing page)."
        )


class OverwriteMissingError(MindyardError):
    """Raised when ``overwrite`` targets a path that does not exist."""

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(
            f"Cannot overwrite '{user_path}': it does not exist (use 'create' for a new page)."
        )


class ReplaceTargetMissingError(MindyardError):
    """Raised when ``replace`` targets a path that does not exist."""

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(f"Cannot replace in '{user_path}': it does not exist.")


class ReplaceNotFoundError(MindyardError):
    """Raised when a ``replace`` op's ``old`` string is not found in the file."""

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(
            f"The 'old' text was not found in '{user_path}'. Did you read the "
            "page with raw=True first? An 'old' taken from rendered output does "
            "not contain the [[wikilinks]] that are on disk."
        )


class ReplaceAmbiguousError(MindyardError):
    """Raised when a ``replace`` op's ``old`` matches more than once."""

    def __init__(self, user_path: str, count: int) -> None:
        self.user_path = user_path
        self.count = count
        super().__init__(
            f"The 'old' text matches {count} times in '{user_path}'. Make it "
            "unique (include surrounding context) or set replace_all=true."
        )


class RenameDestExistsError(MindyardError):
    """Raised when ``rename`` targets an existing destination path."""

    def __init__(self, old_path: str, new_path: str) -> None:
        self.old_path = old_path
        self.new_path = new_path
        super().__init__(
            f"Cannot rename '{old_path}' to '{new_path}': the destination already exists."
        )


class ProtectedFileError(MindyardError):
    """Raised when an op targets a structurally protected file (e.g. the log)."""

    def __init__(self, user_path: str, reason: str) -> None:
        self.user_path = user_path
        self.reason = reason
        super().__init__(f"Cannot modify '{user_path}': {reason}.")


class WriteZoneError(MindyardError):
    """Raised when a write targets a path outside the wiki's mutable zones.

    Writes are confined to the content zones (``wiki/`` and ``raw/``) plus the
    explicit set of mutable root files (index, log, schema). Anything else:
    ``.git/``, generated reports, ad-hoc root files, is rejected, even though it
    resolves inside the wiki root.
    """

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(
            f"Cannot write '{user_path}': writes are confined to wiki/, raw/, "
            "and the index/log/schema files."
        )


class VersionRequiredError(MindyardError):
    """Raised when ``replace``/``overwrite`` omits the required version token."""

    def __init__(self, user_path: str) -> None:
        self.user_path = user_path
        super().__init__(
            f"'expected_version' is required to modify '{user_path}'. Read the "
            "page first (read_page returns its 'version') and pass it back."
        )


class StaleVersionError(MindyardError):
    """Raised when an op's ``expected_version`` no longer matches on disk.

    The page changed since it was last read (another session, or an out-of-band
    edit). Re-read it to get the current content and version, then retry.

    **The current token is deliberately withheld from the message.** Quoting it
    lets a client retry the *same* edit with the fresh token and no re-read,
    which defeats the check. ``replace`` is half-protected (its ``old`` must
    still match the current bytes), but ``overwrite``/``delete``/``rename`` have
    no second anchor, so a blind retry destroys the concurrent edit the writer
    never saw: the exact lost update CAS exists to prevent. An editor such as
    Obsidian, the linter and a second session may all write to the same vault.
    The only way to obtain the current version is ``read_page``, which also
    hands over the current *content*, and reading it is the point.

    ``self.actual`` keeps the token for server-side diagnostics; it just never
    crosses the wire.
    """

    def __init__(self, user_path: str, expected: str, actual: str) -> None:
        self.user_path = user_path
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"'{user_path}' changed on disk since you read it (your version "
            f"{expected} is stale). Re-read the page to get its current content "
            "and version, then rebuild the edit on that content and retry."
        )


class InvalidRegexError(MindyardError):
    """Raised when ``search_wiki(regex=True)`` is given an invalid pattern."""

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        super().__init__(f"Invalid regular expression: '{pattern}'.")


class GitError(MindyardError):
    """Raised when a git operation fails (commit, rollback, etc.)."""
