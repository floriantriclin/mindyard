# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the checks against a vault on disk and write its report.

Reads the wiki zone, the index and ``raw/``. ``get_lint_report`` renders a fresh
report at each call; the ``mindyard lint`` command also writes it to
``LINT_REPORT.md`` at the vault root (outside the write zones).
``fix_table_pipes`` is the only automatic repair: it is deterministic,
idempotent and semantically inert. Everything else needs an editorial decision.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from mindyard.core.render import escape_table_pipes
from mindyard.schema import Wiki

from .checks import RULES, Findings, Page, Snapshot, run_checks
from .markdown import link_key


def _files(base: Path, ignored: set[str], pattern: str) -> list[Path]:
    if not base.is_dir():
        return []
    return sorted(
        p
        for p in base.rglob(pattern)
        if p.is_file()
        and not any(part in ignored or part.startswith(".") for part in p.relative_to(base).parts)
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def build_snapshot(wiki: Wiki) -> Snapshot:
    cfg, lint = wiki.config, wiki.manifest.lint
    root, ignored = cfg.root, set(lint.ignored_dirs)

    def rel(p: Path) -> str:
        return p.relative_to(root).as_posix()

    pages = [Page(rel(p), _read(p)) for p in _files(root / cfg.wiki_dir, ignored, "*.md")]
    index = root / cfg.index_file
    if index.is_file():
        pages.append(Page(cfg.index_file, _read(index)))
    raw = [rel(p) for p in _files(root / cfg.raw_dir, ignored, "*")]
    extra = {link_key(name) for name in (cfg.log_file, cfg.schema_file) if (root / name).is_file()}
    return Snapshot(pages=pages, raw_files=raw, index_rel=cfg.index_file, extra_targets=extra)


def lint_wiki(wiki: Wiki, today: date | None = None) -> Findings:
    return run_checks(build_snapshot(wiki), wiki.manifest, today or date.today())


def fix_table_pipes(wiki: Wiki) -> list[tuple[str, int]]:
    """Escape table-cell alias pipes in place; returns ``(page, count)`` fixed.

    The server already normalises them on write; this repairs pages that reached
    the vault another way (an editor, a direct commit). Changes are left
    uncommitted, for the operator to review.
    """
    fixed: list[tuple[str, int]] = []
    for page in build_snapshot(wiki).pages:
        path = wiki.config.root / page.rel
        new, count = escape_table_pipes(page.text)
        if count:
            path.write_text(new, encoding="utf-8")
            fixed.append((page.rel, count))
    return fixed


def render_report(wiki: Wiki, findings: Findings, generated_at: datetime | None = None) -> str:
    stamp = (generated_at or datetime.now(UTC)).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Lint report: {wiki.config.label}",
        "",
        f"Generated {stamp}. {findings.pages_scanned} pages, {findings.raw_scanned} raw files "
        f"scanned. **{findings.total} issue(s)**; notices are listed but not counted.",
    ]
    for rule_id, rule in RULES.items():
        items = findings.by_rule(rule_id)
        if not items:
            continue
        kind = "issues" if rule.counted else "notices"
        lines += ["", f"## {rule.title} ({len(items)} {kind})", ""]
        lines += [f"- `{f.path}`" + (f": {f.detail}" if f.detail else "") for f in items]
    if not findings.items:
        lines += ["", "Nothing to report."]
    return "\n".join(lines) + "\n"


def write_report(wiki: Wiki, findings: Findings) -> Path:
    path = wiki.config.root / wiki.config.lint_report_file
    path.write_text(render_report(wiki, findings), encoding="utf-8")
    return path
