# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tool-call telemetry: what is actually called, never what is asked.

How a vault is read (which tools, how often, how heavy) is what any later
retrieval layer must be sized on, and a client-side skill cannot be relied on to
report it: it is advisory and may not be loaded. The server always sees the call.

One JSON line per tool call on stderr: timestamp, hashed session, tool name,
wiki id, the *names* of the arguments, their serialised size, the outcome and
the duration. The **values** of the arguments are never recorded: not the
search query, not the page path, not the edit content. The wiki id is the
exception, a short identifier of a vault rather than of a subject. Session ids
are hashed so a log line cannot be replayed against a live session. The tenant
is not recorded either: telemetry describes usage, not who.

That blindness buys the ability to leave telemetry on permanently in a log that
holds no vault content. It never alters a call and never fails one: an emit
error is swallowed. ``MINDYARD_TELEMETRY=0`` disables it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext

# Prefix so the lines are greppable in `docker logs` among FastMCP's own output.
LOG_PREFIX = "mindyard.telemetry "

_SESSION_HASH_LEN = 12


def _short_hash(value: str) -> str:
    """Opaque, stable, non-reversible handle for a session id."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_SESSION_HASH_LEN]


def _arg_names(arguments: object) -> list[str]:
    """Sorted argument *names* of a tool call (never their values)."""
    if not isinstance(arguments, Mapping):
        return []
    return sorted(str(key) for key in arguments)


def _arg_bytes(arguments: object) -> int:
    """Serialised size of the arguments, as a proxy for payload weight."""
    if not isinstance(arguments, Mapping):
        return 0
    try:
        return len(json.dumps(arguments, default=str))
    except (TypeError, ValueError):
        return -1


def _wiki_id(arguments: object) -> str | None:
    """The ``wiki`` argument, the one value safe to record (short identifier)."""
    if not isinstance(arguments, Mapping):
        return None
    value = arguments.get("wiki")
    return value if isinstance(value, str) and len(value) <= 32 else None


def _result_bytes(result: object) -> int:
    """Rough size of the tool result. Best effort: a proxy, not a measurement."""
    try:
        return len(str(result))
    except Exception:  # pragma: no cover - str() on a tool result cannot realistically fail
        return -1


def format_record(record: Mapping[str, object]) -> str:
    """Render one telemetry record as a single greppable line."""
    return LOG_PREFIX + json.dumps(record, ensure_ascii=False, sort_keys=True)


class ToolCallLogMiddleware(Middleware):
    """Emit one line per tool call: name, wiki, argument names, outcome, duration.

    Registered *outermost* (before the access gate) so a call rejected there is
    still counted: an unauthorised attempt is worth seeing in the log.
    """

    def __init__(self, emit: Callable[[str], None] | None = None) -> None:
        self._emit = emit if emit is not None else _emit_stderr

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        started = time.perf_counter()
        message = context.message
        tool = getattr(message, "name", None)
        arguments = getattr(message, "arguments", None)

        session: str | None = None
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is not None:
            try:
                raw_session = fastmcp_context.session_id
            except Exception:  # pragma: no cover - depends on transport internals
                raw_session = None
            if isinstance(raw_session, str) and raw_session:
                session = _short_hash(raw_session)

        record: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "session": session,
            "tool": tool if isinstance(tool, str) else None,
            "wiki": _wiki_id(arguments),
            "args": _arg_names(arguments),
            "arg_bytes": _arg_bytes(arguments),
        }

        try:
            result = await call_next(context)
        except Exception as exc:
            record["outcome"] = "error"
            record["error"] = type(exc).__name__
            record["ms"] = round((time.perf_counter() - started) * 1000, 1)
            self._safe_emit(record)
            raise

        record["outcome"] = "ok"
        record["result_bytes"] = _result_bytes(result)
        record["ms"] = round((time.perf_counter() - started) * 1000, 1)
        self._safe_emit(record)
        return result

    def _safe_emit(self, record: Mapping[str, object]) -> None:
        """Emit, but never let telemetry break a tool call."""
        with contextlib.suppress(Exception):
            self._emit(format_record(record))


def _emit_stderr(line: str) -> None:
    """Default sink: stderr, which Docker captures as the container log."""
    print(line, file=sys.stderr, flush=True)
