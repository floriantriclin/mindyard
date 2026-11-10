# mindyard

Your personal LLM wiki: a git-versioned Markdown vault, served over MCP to
Claude.ai, Claude Desktop, Claude Code or any MCP client.

The model reads, searches and edits your wiki through six tools. The server does
the bookkeeping that keeps the wiki trustworthy, and no model runs on it:

- **every write is a git commit**, applied atomically: a batch of edits lands
  whole or not at all;
- **no lost updates**: editing a page requires the version you read, and a stale
  one is rejected (optimistic concurrency);
- **write zones**: sources in `raw/` are create-only, the index, log and schema
  cannot be deleted, and `wiki.yaml` (the rules) is read-only for the model;
- **the protocol travels with the server**: clients without any skill still get
  the method through the MCP instructions and tool descriptions;
- **a deterministic linter** checks links, orphans, frontmatter and the rules
  your `wiki.yaml` declares (required fields, closed status lists, statuses
  implied by dates).

Status: pre-release (0.1 in development).

## Quickstart

```bash
# not on PyPI yet: from a checkout, run `uv sync` and prefix commands with `uv run`
mindyard init ./data/vaults/garden --demo
mindyard lint ./data/vaults/garden
MINDYARD_DATA_ROOT=./data mindyard serve   # http://127.0.0.1:8787/mcp, no auth, loopback only
```

`mindyard init DIR` without `--demo` creates an empty vault. Every directory under
`<data root>/vaults/` holding a `wiki.yaml` is served as one wiki.

## A vault

```text
garden/
  wiki.yaml    # enforced: layout, entity kinds, lint rules (read-only for the model)
  schema.md    # advisory: what the wiki is about, conventions, for the model
  index.md     # one line per page
  log.md       # one entry per operation
  raw/         # sources, verbatim, create-only
  wiki/        # distilled pages, linked with [[wikilinks]] (Obsidian-compatible)
```

## Authentication

Set `MINDYARD_AUTH`:

| Value | For | Notes |
|---|---|---|
| `none` | local use | refuses to listen beyond loopback |
| `bearer` | Claude Code, Claude Desktop, scripts | `mindyard token new laptop` prints a token once; only its SHA-256 is stored |
| `google` | Claude.ai (OAuth) | needs `MINDYARD_BASE_URL`, `MINDYARD_GOOGLE_CLIENT_ID`, `MINDYARD_GOOGLE_CLIENT_SECRET`, `MINDYARD_ALLOWED_EMAILS` |

Claude Code with a bearer token:

```bash
claude mcp add --transport http mindyard https://wiki.example.org/mcp \
  --header "Authorization: Bearer $MINDYARD_TOKEN"
```

Claude.ai custom connectors accept static headers for some accounts only; OAuth
(`google`) is the route that works everywhere.

## Configuration

| Variable | Default | |
|---|---|---|
| `MINDYARD_DATA_ROOT` | (required) | holds `vaults/`, `tokens.yaml`, `state/` |
| `MINDYARD_AUTH` | `none` | `none`, `bearer`, `google` |
| `MINDYARD_TENANCY` | `single` | `mapped`: several tenants, see below |
| `MINDYARD_HOST`, `MINDYARD_PORT`, `MINDYARD_PATH` | `127.0.0.1`, `8787`, `/mcp` | |
| `MINDYARD_BASE_URL` | | public URL, for OAuth |
| `MINDYARD_ALLOWED_EMAILS` | | comma-separated, verified emails only |
| `MINDYARD_TELEMETRY` | `1` | one log line per tool call; argument values are never logged |

`state/` holds the OAuth proxy's client registrations and tokens. It is not a
cache: deleting it signs every client out.

**Several tenants.** With `MINDYARD_TENANCY=mapped`, `tenants.yaml` maps identities
(issuer and subject, never the email) to tenants, whose vaults live under
`tenants/<tenant>/`. A caller only ever sees its own tenant's wikis; no tool
takes a tenant argument.

## Docker

```bash
cp compose.example.yaml compose.yaml   # adjust user, auth, volume
docker compose up -d
```

Put a TLS reverse proxy in front; the server itself enforces authentication.

## Development

```bash
uv sync
uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest
```

A client skill carrying the editorial method is in `skills/mindyard/`.

Contributions are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Contributors
sign a license agreement ([CLA.md](CLA.md)). Security issues: [SECURITY.md](SECURITY.md).

## License

AGPL-3.0-or-later. See `LICENSE`.
