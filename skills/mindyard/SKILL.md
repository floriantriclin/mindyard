---
name: mindyard
description: Read, query and maintain your personal Markdown wikis through a mindyard MCP server. Use when ingesting a source into a wiki, answering a question from it, saving a fact or decision, or reviewing its lint report.
---

# mindyard

Your wikis are git repositories of Markdown pages, served by a mindyard MCP server.
The server enforces the mechanics (confinement, atomic commits, version checks);
this skill carries the editorial method. Both apply without it, through the
server instructions, but less well.

## Every session

1. Call `list_wikis`. Pick the one wiki the request is about; if it is unclear,
   ask. Pass that `wiki` on every call.
2. Read its schema file (`schema.md` unless the wiki says otherwise) before any
   write: it defines the domain, the page kinds and the conventions.
3. Before any `write_batch`, show the plan: target wiki, each operation, and the
   split if more than one batch is needed (index and log in the last one). Write
   only after explicit agreement.

## Reading and editing

- `read_page` renders for display: wikilinks are stripped. Never show `[[...]]`
  to the user.
- To edit, read the page again with `raw=True`: you get the bytes on disk and a
  `version`. Build `replace` ops on those bytes and pass `expected_version`.
- A stale version is rejected: re-read, rebuild the edit on the new content.
  Never resend the same payload.
- Prefer `replace` over `overwrite`. `raw/` is create-only. `wiki.yaml` is
  read-only for you; propose changes to the user instead. One exception: in a
  new vault whose `wiki.yaml` still holds the `# mindyard:bootstrap` line, define
  it with the user: ask its purpose, propose a small first draft (two to four
  kinds of pages), then overwrite it once, without that line, in the same batch
  as `schema.md`. The owner adds kinds later by hand: start small.
- If a batch is refused and fixing it changes the agreed plan, present the new
  plan and wait for agreement again.

## Operations

### ingest: a source becomes knowledge
1. Store the source verbatim in `raw/`, named `YYYY-MM-DD-short-slug.md`.
2. Distil it: update existing pages first (search before creating), create a
   page only for a subject that has none. Cite the raw file in `sources`.
3. Add or update the index lines, append a log entry by replacing the log's
   sentinel line, all in the same batch as the pages.

### query: answer from the wiki
Search (`search_wiki`), read the relevant pages, answer citing them. Say plainly
what the wiki does not contain rather than filling the gap from memory.

### save: record a fact or a decision
Find the page it belongs on, add it with its date and source, and log it.

### lint: review hygiene
Read `get_lint_report`. Fix what needs judgment (orphans, missing fields,
unwritten pages worth writing); leave the user the choices that are theirs.

## Pitfalls

- Keep each `write_batch` under about 30 kB of arguments; split up front.
- `rename` does not rewrite links: fix them with `replace` in the same batch.
- In a table, an aliased link must escape its pipe: `[[page\|alias]]` (the
  server fixes it on write and reports it under `normalized`).
