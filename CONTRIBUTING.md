# Contributing to mindyard

Thanks for considering a contribution. Bug reports, documentation fixes and
code are all welcome.

## Before your first pull request

mindyard asks every contributor to accept a Contributor License Agreement
([CLA.md](CLA.md)). You keep the copyright on your work; you grant the
maintainer a license that includes the right to sublicense, which keeps a
commercial license possible alongside the AGPL. A bot asks you to sign when you
open your first pull request; it takes one click.

## Development

```bash
uv sync
uv run ruff check && uv run ruff format --check && uv run mypy && uv run pytest
```

All four must pass; CI runs them on every pull request.

Ground rules:

- **No model calls on the server.** mindyard executes and records; it does not reason.
- **The invariants are tested, keep them tested**: path confinement, optimistic
  concurrency (a stale-version error never quotes the current version), atomic
  and per-wiki serialised `write_batch`, create-only `raw/`, `wiki.yaml` outside
  the write zones, tenant derived from identity and never from an argument.
- **No real personal data**, in fixtures, examples or docs. Use invented names.
- Code, docstrings and docs in English; every Python file carries the
  `SPDX-License-Identifier: AGPL-3.0-or-later` header.

## Reporting a vulnerability

Do not open a public issue: see [SECURITY.md](SECURITY.md).
