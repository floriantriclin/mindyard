# SPDX-License-Identifier: AGPL-3.0-or-later
"""The access log keeps paths, never query strings."""

from __future__ import annotations

import logging

from mindyard.mcp.accesslog import RedactQueryFilter


def _record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", path, "1.1", 302),
        None,
    )


def test_query_is_redacted() -> None:
    record = _record("/auth/callback?code=SECRET&state=abc")
    assert RedactQueryFilter().filter(record)
    assert "SECRET" not in record.getMessage()
    assert '"GET /auth/callback?… HTTP/1.1" 302' in record.getMessage()


def test_plain_path_is_untouched() -> None:
    record = _record("/mcp")
    RedactQueryFilter().filter(record)
    assert record.getMessage() == '1.2.3.4:5 - "GET /mcp HTTP/1.1" 302'
