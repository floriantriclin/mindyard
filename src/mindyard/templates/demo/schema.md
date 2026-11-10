# Schema: Harbor Lane community garden

## Purpose

A shared memory for the volunteers of an imaginary community garden: what grows
where, what worked, what is coming up. Everything in this vault is fictitious.

## Layout

- `raw/`: notes and sources, verbatim and create-only.
- `wiki/plants/`: one page per crop (`entity_kind: plant`).
- `wiki/events/`: dated events (`entity_kind: event`, with `start_date`).
- `wiki/concepts/`: practices and techniques (`entity_kind: concept`).

## Conventions

- File names are lower-case slugs: `wiki/plants/tomato.md`.
- Each page cites its sources in the `sources` frontmatter list.
- An event's `status` follows its dates; the linter flags a stale one.
- A plant's `status` is one of: planned, growing, harvested, retired.
