# mindyard

An open source MCP server that serves personal LLM wikis: Markdown vaults versioned in
git, read and edited by Claude.ai, Claude Desktop, Claude Code or any MCP client.

## Stack

Python 3.12+, `uv`, FastMCP (pinned below 3.5, see `src/mindyard/auth/consent.py`),
streamable HTTP transport. No model runs on the server: it executes and records, it
does not reason.

## Layout

Under `src/mindyard/`:

- `core/`: pure domain (paths, versions, `write_batch`, git, search, rendering). Imports
  nothing else from the package.
- `schema/`: `wiki.yaml`, the enforced contract of a vault, and vault discovery.
- `tenancy/`: tenants resolved from the caller's identity, request context.
- `auth/`: auth backends (none, bearer, google), access policies, stable consent page.
- `mcp/`: the six tools, the per-request gate, telemetry, access log, assembly.
- `lint/`: generic checks plus the rules a `wiki.yaml` declares.
- `cli.py`, `init.py`, `templates/` (blank and demo vaults), `static/` (icons).

## Commands

- Install: `uv sync`
- Gates, all four before any commit: `uv run ruff check`, `uv run ruff format --check`,
  `uv run mypy`, `uv run pytest`
- Provenance: `scripts/check-provenance.sh` (also run by the maintainer's local
  pre-commit hook) scans the working tree against a private pattern list.
- Try it: `uv run mindyard init <tmp>/vaults/garden --demo`, then
  `MINDYARD_DATA_ROOT=<tmp> uv run mindyard serve`

## Invariants (tested, keep them tested)

- Path confinement: every path resolves inside its wiki root; a symlinked vault that
  leaves its tenant root is refused at load.
- Optimistic concurrency: modifying, deleting or renaming an existing file requires the
  version from `read_page`; `StaleVersionError` never quotes the current version.
- `write_batch` is the only write path: validated whole, then applied in one commit,
  rolled back on failure, serialised per wiki.
- Write zones: `raw/` is create-only; index, log and schema cannot be deleted or
  renamed; `wiki.yaml` is outside the write zones.
- The tenant comes from the caller's identity (issuer and subject, never the email) and
  is never a tool argument.
- Startup refuses configurations that would expose vaults (no auth beyond loopback,
  partial OAuth, Google without an allowlist in single-tenant mode).

## Conventions

- Code, identifiers, docstrings, docs and commit messages in English.
- Every Python file starts with `# SPDX-License-Identifier: AGPL-3.0-or-later`.
- No real personal data in fixtures, examples or docs: invented names only.
- External contributions require the CLA (`CLA.md`).
