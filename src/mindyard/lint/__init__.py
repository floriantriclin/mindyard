# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic linter: generic checks plus the rules a wiki declares."""

from .checks import RULES, Finding, Findings
from .runner import build_snapshot, fix_table_pipes, lint_wiki, render_report, write_report

__all__ = [
    "RULES",
    "Finding",
    "Findings",
    "build_snapshot",
    "fix_table_pipes",
    "lint_wiki",
    "render_report",
    "write_report",
]
