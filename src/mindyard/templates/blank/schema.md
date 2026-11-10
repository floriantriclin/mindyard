# Schema

This file tells the model what this wiki is about and how to write in it. It is
advisory prose: the enforced rules live in `wiki.yaml`. Edit it freely, or ask
your assistant to propose changes.

## Purpose

What this wiki is for, in two or three sentences.

## Layout

- `raw/`: sources, kept verbatim. Create-only: never edited after ingestion.
- `wiki/`: distilled pages, one subject per page, linked with `[[wikilinks]]`.
- `index.md`: one line per page, a pointer rather than a summary.
- `log.md`: one entry per operation, newest just above the sentinel line.

## Page conventions

Every page under `wiki/` opens with a YAML frontmatter block:

```yaml
---
title: Page title
entity_kind: concept
sources: ["[[raw/2026-01-01-source-name]]"]
updated: 2026-01-01
---
```

## Operations

- **ingest**: store the source in `raw/`, distil it into new or updated pages,
  add index lines and a log entry, all in one batch.
- **query**: answer from the wiki, citing the pages used; say what is missing.
- **save**: record a new fact or decision on the right page, with its source.
- **lint**: read the lint report and fix what needs an editorial decision.
