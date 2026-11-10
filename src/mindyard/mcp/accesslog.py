# SPDX-License-Identifier: AGPL-3.0-or-later
"""Keep query strings out of the HTTP access log.

The OAuth routes carry secrets in their query (``/auth/callback?code=...``,
``/authorize?code_challenge=...&state=...``), and uvicorn logs the full request
line. The access log stays useful with the path alone: which route, which
status, from where.
"""

from __future__ import annotations

import logging

ACCESS_LOGGER = "uvicorn.access"


class RedactQueryFilter(logging.Filter):
    """Replace everything after ``?`` in the logged path with ``?…``."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        # uvicorn: (client_addr, method, full_path, http_version, status_code)
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2]
            if "?" in path:
                record.args = (args[0], args[1], path.split("?", 1)[0] + "?…", *args[3:])
        return True


def install() -> None:
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, RedactQueryFilter) for f in logger.filters):
        logger.addFilter(RedactQueryFilter())
