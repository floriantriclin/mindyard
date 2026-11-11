# SPDX-License-Identifier: AGPL-3.0-or-later
"""The mindyard.dev waitlist endpoint (site/waitlist/waitlist.py)."""

import http.client
import importlib.util
import sqlite3
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib.parse import urlencode

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "site" / "waitlist" / "waitlist.py"
pytestmark = pytest.mark.skipif(not SOURCE.exists(), reason="site/ is not shipped in sdists")


@pytest.fixture(scope="module")
def wl() -> ModuleType:
    spec = importlib.util.spec_from_file_location("waitlist", SOURCE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def server(wl: ModuleType, tmp_path: Path) -> Iterator[tuple[int, Path]]:
    db = tmp_path / "w.sqlite"
    wl.connect(db).close()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), wl.make_handler(db))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1], db
    httpd.shutdown()
    httpd.server_close()


def post(port: int, fields: dict[str, str], path: str = "/api/waitlist") -> tuple[int, str, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    body = urlencode(fields)
    conn.request("POST", path, body, {"Content-Type": "application/x-www-form-urlencoded"})
    resp = conn.getresponse()
    result = resp.status, resp.getheader("Location") or "", resp.read().decode()
    conn.close()
    return result


def rows(db: Path) -> list[tuple[str, str | None]]:
    with sqlite3.connect(db) as conn:
        return list(conn.execute("SELECT email, price FROM signup ORDER BY email"))


VALID = {"email": "Ada@Example.org", "price": "3to6", "consent": "yes", "website": ""}


def test_valid_signup_is_stored_and_redirected(server: tuple[int, Path]) -> None:
    port, db = server
    status, location, _ = post(port, VALID)
    assert (status, location) == (303, "/thanks.html")
    assert rows(db) == [("ada@example.org", "3to6")]


def test_signing_up_again_does_not_duplicate_and_keeps_a_price(server: tuple[int, Path]) -> None:
    port, db = server
    post(port, VALID)
    post(port, {**VALID, "price": ""})
    assert rows(db) == [("ada@example.org", "3to6")]
    post(port, {**VALID, "price": "gt10"})
    assert rows(db) == [("ada@example.org", "gt10")]


def test_honeypot_looks_successful_but_stores_nothing(server: tuple[int, Path]) -> None:
    port, db = server
    status, location, _ = post(port, {**VALID, "website": "http://spam.example"})
    assert (status, location) == (303, "/thanks.html")
    assert rows(db) == []


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"consent": ""}, "consent box"),
        ({"email": "not-an-email"}, "does not look valid"),
        ({"email": "a@b"}, "does not look valid"),
        ({"price": "free"}, "Unknown price"),
    ],
)
def test_invalid_submissions_are_refused(
    server: tuple[int, Path], change: dict[str, str], message: str
) -> None:
    port, db = server
    status, _, body = post(port, {**VALID, **change})
    assert status == 400
    assert message in body
    assert rows(db) == []


def test_other_paths_and_oversized_bodies_are_refused(server: tuple[int, Path]) -> None:
    port, _ = server
    assert post(port, VALID, "/api/other")[0] == 404
    assert post(port, {**VALID, "website": "", "pad": "x" * 5000})[0] == 400


def test_counts_separate_declared_prices_from_refusals(wl: ModuleType, tmp_path: Path) -> None:
    conn = wl.connect(tmp_path / "c.sqlite")
    for email, price in [
        ("a@x.org", "lt3"),
        ("b@x.org", "none"),
        ("c@x.org", ""),
        ("d@x.org", "gt10"),
    ]:
        wl.record(conn, email, price)
    c = wl.counts(conn)
    assert (c["signups"], c["priced"], c["none"], c["unanswered"]) == (4, 2, 1, 1)
