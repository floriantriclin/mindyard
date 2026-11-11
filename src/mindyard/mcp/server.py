# SPDX-License-Identifier: AGPL-3.0-or-later
"""The MCP surface: six tools over the caller's wikis.

A thin layer. Each tool reads the tenant bound to the request, validates the
``wiki`` argument against that tenant's wikis only, and delegates to
:mod:`mindyard.core.operations`. Domain errors become ``ToolError`` with their
message verbatim (they never carry server paths).
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import Icon, ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import FileResponse

from mindyard import __version__
from mindyard.auth import AccessPolicy, AuthBackend
from mindyard.core import operations
from mindyard.core.config import CONFIG_FILE, WikiConfig
from mindyard.core.errors import ConfigRejectedError, MindyardError
from mindyard.core.search import SearchHit
from mindyard.identity import git_author
from mindyard.lint import lint_wiki, render_report
from mindyard.schema import ManifestError, Wiki, check_definition, load_manifest
from mindyard.tenancy import TenantResolver, current_tenant

from .middleware import TenantGateMiddleware, current_identity
from .telemetry import ToolCallLogMiddleware

_STATIC = Path(__file__).resolve().parent.parent / "static"
# Public routes, like a health check: clients show the icon before signing in.
_ICONS = {
    "/icon-96.png": ("icon-96.png", "image/png"),
    "/favicon.ico": ("icon-96.png", "image/png"),
    "/icon.svg": ("icon.svg", "image/svg+xml"),
}

# Delivered in the MCP ``initialize`` response, so the protocol reaches the model
# even when no client-side skill is loaded. The tool docstrings repeat the rules,
# since the tool schema is always delivered.
SERVER_INSTRUCTIONS = """\
mindyard: personal Markdown knowledge bases (wikis), each a git repository.

Routing: call list_wikis first; pick ONE wiki and pass it on every call. Read
its schema file (schema.md by default) before writing: it holds the wiki's
domain and conventions. Before any write_batch, present the plan to the user
(target wiki, every operation, and the split if several batches are needed,
with index and log in the last) and proceed only on explicit agreement.

New vault: if the schema file is still the blank template (placeholders such as
'What this wiki is for'), offer to define the wiki with the user first: ask what
it is for and which kinds of pages it will hold, then propose schema.md and,
while wiki.yaml still holds its '# mindyard:bootstrap' line, a complete
wiki.yaml (label, description, entities with their required fields and closed
status lists). Both go in one batch once the user agrees; wiki.yaml is then
locked for good.

Reading vs editing: read_page renders for display (wikilinks stripped); never
show '[[...]]' to the user. To edit a page you MUST first read it with raw=True
to get the verbatim bytes AND its version; build the edit on those bytes and
pass the version back as expected_version.

Writing (write_batch, the only write path): a list of typed ops applied
atomically in one commit: create / overwrite / replace / delete / rename.
Prefer replace (surgical) over overwrite. Modifying, deleting or renaming an
existing file requires expected_version from read_page; a stale token is
rejected, so re-read and rebuild. raw/ is create-only. The log, index and
schema files cannot be deleted or renamed; the log grows by replacing its
sentinel line. Writes are confined to the wiki and raw zones plus the
index/log/schema files; wiki.yaml is read-only, except for that one-time
definition. Include a log entry in the same batch.
"""


def _tool_errors[F: Callable[..., object]](fn: F) -> F:
    @functools.wraps(fn)
    def wrapper(*args: object, **kwargs: object) -> object:
        try:
            return fn(*args, **kwargs)
        except MindyardError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper  # type: ignore[return-value]


def _wiki(wiki: str) -> WikiConfig:
    """The caller's wiki ``wiki``. Never another tenant's."""
    return current_tenant().wiki_set().get_wiki(wiki)


def _read_only(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, readOnlyHint=True, openWorldHint=False)


# Parameter descriptions travel in the tool's JSON schema, which every client
# receives; they are what an agent reads to fill each argument.
WikiId = Annotated[str, Field(description="Wiki id, as returned by list_wikis.")]
Scope = Annotated[
    str,
    Field(
        description="Zone: 'wiki' (distilled pages, default), 'raw' (verbatim sources) "
        "or 'all' (both). Index, log and schema files sit at the wiki root, outside "
        "every zone: open them with read_page."
    ),
]


def build_server(
    backend: AuthBackend,
    policy: AccessPolicy,
    resolver: TenantResolver,
    *,
    telemetry: bool = True,
    website_url: str | None = None,
) -> FastMCP[Any]:
    mcp: FastMCP[Any] = FastMCP(
        "mindyard",
        version=__version__,
        instructions=SERVER_INSTRUCTIONS,
        mask_error_details=True,
        auth=backend.provider(),
        website_url=website_url,
        icons=(
            [Icon(src=f"{website_url}/icon-96.png", mimeType="image/png", sizes=["96x96"])]
            if website_url
            else None
        ),
    )
    if telemetry:
        mcp.add_middleware(ToolCallLogMiddleware())
    mcp.add_middleware(TenantGateMiddleware(backend, policy, resolver))

    for route, (filename, media_type) in _ICONS.items():

        async def icon(
            _request: Request, filename: str = filename, media_type: str = media_type
        ) -> FileResponse:
            return FileResponse(_STATIC / filename, media_type=media_type)

        mcp.custom_route(route, methods=["GET"])(icon)

    @mcp.tool(annotations=_read_only("List wikis"))
    @_tool_errors
    def list_wikis() -> list[dict[str, str]]:
        """List the caller's wikis as [{id, label, description}].

        Call it first in a session: every other tool takes one of these ids as
        'wiki'. An empty list means no wiki is set up for this account.
        """
        wikis = current_tenant().wikis
        return [
            {
                "id": wid,
                "label": w.config.label,
                "description": w.config.description,
            }
            for wid, w in sorted(wikis.items())
        ]

    @mcp.tool(annotations=_read_only("Read page"))
    @_tool_errors
    def read_page(
        wiki: WikiId,
        path: Annotated[
            str,
            Field(
                description="File path relative to the wiki root, e.g. 'index.md' or "
                "'wiki/topic.md' (as listed by list_pages or search_wiki)."
            ),
        ],
        raw: Annotated[
            bool, Field(description="Verbatim bytes, wikilinks kept: use before editing.")
        ] = False,
        offset: Annotated[int, Field(description="First line to return, 1-based.")] = 1,
        limit: Annotated[
            int | None, Field(description="Maximum number of lines; all when omitted.")
        ] = None,
    ) -> dict[str, object]:
        """Read one file of the target wiki (confined to its root).

        Use it to open a page found with list_pages or search_wiki, and the index,
        log and schema files at the wiki root. A missing path or one outside the
        wiki is refused with an error.

        Default: rendered for display, Obsidian wikilinks stripped, so never show
        '[[...]]' to the user. Pass raw=True to get the verbatim bytes before
        editing a page, so write_batch keeps the '[[...]]' syntax on disk.

        offset is 1-based and limit caps the lines returned. Returns {content,
        version, total_lines, start_line, end_line, truncated}. Pass 'version'
        back as 'expected_version' when modifying this page.
        """
        return dict(operations.read_page(_wiki(wiki), path, raw, offset, limit))

    @mcp.tool(annotations=_read_only("List pages"))
    @_tool_errors
    def list_pages(
        wiki: WikiId,
        scope: Scope = "wiki",
        prefix: Annotated[
            str,
            Field(
                description="Keep only paths starting with this, relative to the wiki "
                "root, e.g. 'wiki/people/'. Empty: no filter."
            ),
        ] = "",
        limit: Annotated[int, Field(description="Maximum number of paths returned.")] = 200,
    ) -> dict[str, object]:
        """List the Markdown files of a zone, to browse a wiki by its structure.

        To find pages by their content, use search_wiki instead; to open one, pass
        its path to read_page. Returns {pages, truncated, total}: paths relative to
        the wiki root, sorted and capped at limit; total counts every match and
        truncated says the list was cut.
        """
        return dict(operations.list_pages(_wiki(wiki), scope, prefix, limit))

    @mcp.tool(annotations=_read_only("Search wiki"))
    @_tool_errors
    def search_wiki(
        wiki: WikiId,
        query: Annotated[str, Field(description="Text to find, case-insensitive.")],
        scope: Scope = "wiki",
        max_results: Annotated[int, Field(description="Stop after this many matching lines.")] = 30,
        regex: Annotated[
            bool, Field(description="Treat query as a regular expression (default: literal).")
        ] = False,
    ) -> list[SearchHit]:
        """Find the lines of a wiki that contain a text, to locate pages by content.

        Returns [{page, line, text}], one entry per matching line. Read the full
        page with read_page (offset=line jumps to the match); to browse by path,
        use list_pages. An invalid regular expression is refused with an error.
        """
        return list(operations.search_wiki(_wiki(wiki), query, scope, max_results, regex))

    @mcp.tool(annotations=_read_only("Lint report"))
    @_tool_errors
    def get_lint_report(wiki: WikiId) -> str:
        """Lint the wiki now and return the report, as Markdown.

        The report lists broken links, orphan pages, frontmatter problems and
        breaches of the rules the wiki declares; notices are listed but not
        counted. It reflects the files as they are at the call, recent edits
        included, and writes nothing. Use it to review a wiki's health, before a
        clean-up batch, and after one to check the result.
        """
        _wiki(wiki)  # an unknown id fails here, with the list of valid ones
        vault = current_tenant().wikis[wiki]
        return render_report(vault, lint_wiki(vault))

    @mcp.tool(
        annotations=ToolAnnotations(
            title="Write batch (commits changes)",
            readOnlyHint=False,
            destructiveHint=True,
            idempotentHint=False,
            openWorldHint=False,
        )
    )
    @_tool_errors
    def write_batch(
        wiki: WikiId,
        edits: Annotated[
            list[operations.Operation],
            Field(description="Edit operations, applied in order; see the tool description."),
        ],
        message: Annotated[str, Field(description="Commit message describing the change.")],
    ) -> dict[str, object]:
        """Transactionally apply typed edit operations in one git commit.

        Call it only after the user agreed to the plan (target wiki, every
        operation, any split into several batches). Keep each call under about
        30 kB of arguments: split up front, with index and log in the last batch.

        Each edit is one {op, ...}, applied in order (chained on the same path):
        - create:    {op, path, content}; fails if the path exists.
        - overwrite: {op, path, content, expected_version}; full rewrite.
        - replace:   {op, path, old, new, expected_version, replace_all?};
          surgical edit, 'old' must be unique unless replace_all=true. Read the
          page with raw=True first so 'old' matches the bytes on disk.
        - delete:    {op, path, expected_version}.
        - rename:    {op, path, new_path, expected_version}; wikilinks to the old
          name are not rewritten, fix them with replace ops in the same batch.

        expected_version is the token from read_page; required to modify, delete
        or rename an existing file, ignored for a path created earlier in this
        batch. Writes stay under the wiki and raw zones or the index/log/schema
        files; raw/ is create-only; the log, index and schema cannot be deleted or
        renamed. wiki.yaml is read-only, except once: while it still holds its
        '# mindyard:bootstrap' line, an overwrite may define it (valid config,
        same layout and log, marker line removed), then it locks. Everything is
        validated first: on any failure nothing is written or committed. Returns
        {commit, applied}.
        """
        cfg = _wiki(wiki)
        author = git_author(current_identity())

        def check(current: str, proposed: str) -> None:
            try:
                check_definition(current, proposed, cfg.root.name)
            except ManifestError as exc:
                raise ConfigRejectedError(str(exc)) from exc

        result = operations.write_batch(cfg, edits, message, author, check)
        config = (cfg.root / CONFIG_FILE).resolve()
        if any((cfg.root / entry["path"]).resolve() == config for entry in result["applied"]):
            # The new definition takes effect at once: labels, entity kinds and
            # lint rules. Layout is unchanged (check_definition), so are the zones.
            manifest = load_manifest(cfg.root)
            current_tenant().wikis[wiki] = Wiki(manifest.to_config(wiki, cfg.root), manifest)
        return dict(result)

    return mcp
