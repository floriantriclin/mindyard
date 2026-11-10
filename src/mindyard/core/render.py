# SPDX-License-Identifier: AGPL-3.0-or-later
"""Display rendering and write normalisation (deterministic, no model calls).

Obsidian **wikilinks** (`[[target]]`, `[[target|alias]]`) are only meaningful in
the local Obsidian vault; over MCP they are noise, a client renders them as raw
`[[brackets]]`. ``read_page`` strips them by default so the LLM never shows a
wikilink. The raw bytes stay reachable via ``raw=True`` for the edit/lint path,
which must preserve ``[[...]]`` verbatim when writing back.

Rules:
- ``[[target|alias]]`` -> keep ``alias`` (it is real prose in the sentence).
- ``[[target]]``       -> remove entirely (bare target is just a filename, of no
  use in display); drop a wrapping empty ``(...)`` and tidy stray whitespace.

The write path has one normalisation of its own, :func:`escape_table_pipes`: an
aliased wikilink in a Markdown table cell must escape its pipe (``[[a\\|b]]``),
or the bare ``|`` is read as a column separator and breaks *both* the table and
the link. Models forget this constantly, so it is applied on write and the
mistake becomes impossible rather than merely caught by the linter afterwards.
Rejecting the batch instead would be worse: an atomic batch carrying a whole page
would have to be regenerated over a missing backslash.

This is pure string work (regex), not reasoning: it stays inside the
"no LLM server-side" invariant. The rewrite is semantically inert (same target,
same alias) and idempotent, which is what makes it safe to apply silently, the
count is still reported back to the caller in ``write_batch``'s result.
"""

from __future__ import annotations

import re

# Inside of a wikilink: the shortest run of same-line characters that does not
# contain the closing "]]", and, for the target/alias halves of an aliased
# link, no pipe either (the pipe is the separator). Excluding *every* bracket
# (the previous rule) left any link whose target carries one unrendered, and a
# raw/ attachment legitimately does ("[[raw/notes/[important] Note…]]"), so
# read_page leaked raw "[[...]]" to the client on the pages citing it.
_INNER = r"(?:(?!\]\])[^\n])+?"
_INNER_NO_PIPE = r"(?:(?!\]\])[^\n|])+?"

# Aliased link: capture the alias (text after the pipe). Optional leading '!'
# for Obsidian embeds (![[...]]).
_ALIASED = re.compile(rf"!?\[\[{_INNER_NO_PIPE}\|({_INNER_NO_PIPE})\]\]")

# Bare link wrapped in its own parentheses, e.g. " ([[2026-03-14-reading-group]])":
# remove the whole parenthesised reference, including the leading space.
_BARE_IN_PARENS = re.compile(rf"[ \t]*\(\s*!?\[\[{_INNER}\]\]\s*\)")

# Any remaining bare link.
_BARE = re.compile(rf"!?\[\[{_INNER}\]\]")

# Tidy passes applied after removals.
_MULTISPACE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:!?)])")


def strip_wikilinks(text: str) -> str:
    """Return ``text`` with Obsidian wikilinks removed for display.

    Aliased links collapse to their alias; bare links are dropped. The result is
    plain prose with no ``[[...]]`` and no dangling empty parentheses.
    """
    # Order matters: resolve aliased links first so "[[a|b]]" becomes "b" and is
    # not caught by the bare patterns below.
    text = _ALIASED.sub(lambda m: m.group(1), text)
    text = _BARE_IN_PARENS.sub("", text)
    text = _BARE.sub("", text)
    # Clean up whitespace artefacts left by the removals.
    text = _MULTISPACE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    return text


# Any wikilink, capturing its inside, used to rewrite the alias pipe on write.
_WIKILINK = re.compile(rf"!?\[\[({_INNER})\]\]")

# A pipe with no backslash in front of it: an *unescaped* alias separator.
_UNESCAPED_PIPE = re.compile(r"(?<!\\)\|")


def escape_table_pipes(text: str) -> tuple[str, int]:
    """Escape unescaped alias pipes in wikilinks that sit in a table cell.

    On a table row (a line whose stripped form starts with ``|``), an unescaped
    ``|`` inside ``[[...]]`` is rewritten to ``\\|``, so it is no longer read as
    a column separator. Pipes already escaped, links outside a table, and the
    cell separators themselves are left alone.

    Deterministic, idempotent (a second pass changes nothing) and semantically
    inert: same target, same alias, only the escaping changes. Line endings are
    preserved.

    Returns ``(new_text, n_fixed)``, ``n_fixed`` counting the wikilinks rewritten.
    """
    n_fixed = 0

    def _escape(match: re.Match[str]) -> str:
        nonlocal n_fixed
        inner = match.group(1)
        if not _UNESCAPED_PIPE.search(inner):
            return match.group(0)
        n_fixed += 1
        return f"[[{_UNESCAPED_PIPE.sub(r'\\|', inner)}]]"

    out: list[str] = []
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("|"):
            line = _WIKILINK.sub(_escape, line)
        out.append(line)
    return "".join(out), n_fixed
