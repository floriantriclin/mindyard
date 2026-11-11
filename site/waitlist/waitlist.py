# SPDX-License-Identifier: AGPL-3.0-or-later
"""Waitlist for the hosted mindyard: one form endpoint and a counter.

Standard library only, so it runs on any Python 3.12+ without installing anything.

    python3 waitlist.py serve --db waitlist.sqlite [--host 127.0.0.1] [--port 8109]
    python3 waitlist.py count --db waitlist.sqlite

The form posts to /api/waitlist and gets a 303 to /thanks.html, so it works without
JavaScript. Stored per sign-up: email, optional price bracket, date, and the version
of the consent text. No IP address, no cookie. A filled honeypot field is answered
like a success and stored nowhere.
"""

import argparse
import re
import sqlite3
import sys
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

PATH = "/api/waitlist"
THANKS = "/thanks.html"
CONSENT_VERSION = "2026-11-11"
MAX_BODY = 4096
PRICES = ("lt3", "3to6", "6to10", "gt10", "none")
# Deliberately loose: one @, a dot in the domain, no spaces. Typos are the user's.
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signup (
    email TEXT PRIMARY KEY,
    price TEXT,
    created TEXT NOT NULL,
    consent TEXT NOT NULL
)
"""

ERROR_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Sign-up not recorded · mindyard</title>
<style>body{{font:1.0625rem/1.6 system-ui,sans-serif;max-width:36rem;margin:4rem auto;
padding:0 1.25rem}}</style>
</head><body><main><h1>Sign-up not recorded</h1><p>{reason}</p>
<p><a href="/#hosted">Back to the form</a></p></main></body></html>
"""


class Invalid(ValueError):
    """A form submission that cannot be recorded; the message is shown to the user."""


def connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(SCHEMA)
    return conn


def parse(body: str) -> dict[str, str] | None:
    """Validate a submission. None means a bot: answer as if recorded, store nothing."""
    form = {k: v[0].strip() for k, v in parse_qs(body, keep_blank_values=True).items()}
    if form.get("website"):
        return None
    email = form.get("email", "").lower()
    if len(email) > 254 or not EMAIL.match(email):
        raise Invalid("The email address does not look valid.")
    if form.get("consent") != "yes":
        raise Invalid("Please tick the consent box: without it, your email cannot be kept.")
    price = form.get("price", "")
    if price and price not in PRICES:
        raise Invalid("Unknown price bracket.")
    return {"email": email, "price": price}


def record(conn: sqlite3.Connection, email: str, price: str) -> None:
    """Insert a sign-up; signing up again keeps the date and updates a given price."""
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with conn:
        conn.execute(
            "INSERT INTO signup (email, price, created, consent) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(email) DO UPDATE SET price = COALESCE(excluded.price, price), "
            "consent = excluded.consent",
            (email, price or None, now, CONSENT_VERSION),
        )


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Sign-ups, and people who declared a price they would pay ('none' excluded)."""
    rows = dict(conn.execute("SELECT COALESCE(price, ''), COUNT(*) FROM signup GROUP BY 1"))
    result = {"signups": sum(rows.values())}
    result["priced"] = sum(n for p, n in rows.items() if p and p != "none")
    for p in (*PRICES, ""):
        result[p or "unanswered"] = rows.get(p, 0)
    return result


def make_handler(db: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "mindyard-waitlist"
        sys_version = ""

        def do_POST(self) -> None:
            if self.path != PATH:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            body = self.rfile.read(length).decode("utf-8", "replace")
            try:
                fields = parse(body)
            except Invalid as e:
                self._page(HTTPStatus.BAD_REQUEST, ERROR_PAGE.format(reason=e))
                return
            if fields is not None:
                conn = connect(db)
                try:
                    record(conn, fields["email"], fields["price"])
                finally:
                    conn.close()
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", THANKS)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _page(self, status: HTTPStatus, html: str) -> None:
            data = html.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            # Request lines only, never bodies; nginx keeps the access log.
            sys.stderr.write(f"{self.command} {self.path} {args[1] if len(args) > 1 else ''}\n")

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the form endpoint")
    serve.add_argument("--db", type=Path, required=True)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8109)
    count = sub.add_parser("count", help="print sign-up counts")
    count.add_argument("--db", type=Path, required=True)
    args = parser.parse_args(argv)

    connect(args.db).close()
    if args.cmd == "count":
        conn = connect(args.db)
        for key, value in counts(conn).items():
            print(f"{key:<12}{value}")
        conn.close()
        return 0
    server = ThreadingHTTPServer((args.host, args.port), make_handler(args.db))
    print(f"waitlist on http://{args.host}:{args.port}{PATH}", file=sys.stderr)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
