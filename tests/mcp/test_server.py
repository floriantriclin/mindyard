# SPDX-License-Identifier: AGPL-3.0-or-later
"""End to end through an in-memory MCP client: tools, gate, tenants."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import AccessToken, AuthProvider

from mindyard.auth import AllowAll, AllowAuthenticated, EmailAllowlist, NoAuth
from mindyard.identity import Identity
from mindyard.mcp import build_server
from mindyard.tenancy import SingleTenantResolver, load_mapped_resolver, load_tenant
from tests.conftest import git_init, make_wiki

ISSUER = "https://issuer.example"
# A refusal during the handshake reaches the client as a failed initialize, so
# its wording is the SDK's; the gate's own message is logged server side.
DENIED = "Access denied|Invalid request parameters"


@dataclass
class FakeBackend:
    """Stands in for an auth backend: the test decides who is calling."""

    caller: Identity | None = None
    name: str = "fake"

    def provider(self) -> AuthProvider | None:
        return None

    def identity(self, token: AccessToken | None) -> Identity | None:
        return self.caller


def _vault(base: Path, wiki_id: str, label: str) -> Path:
    root = base / wiki_id
    make_wiki(root)
    (root / "wiki.yaml").write_text(
        f"mindyard: 1\nlabel: {label}\ndescription: About {label}\n", encoding="utf-8"
    )
    (root / "wiki" / "owner.md").write_text(f"{label} [[x|page]]\n", encoding="utf-8")
    git_init(root)
    return root


def _data(result: Any) -> Any:
    return result.structured_content.get("result", result.structured_content)


@pytest.fixture
def single(tmp_path: Path) -> FastMCP[Any]:
    _vault(tmp_path / "vaults", "notes", "Notes")
    resolver = SingleTenantResolver(load_tenant("default", tmp_path / "vaults"))
    return build_server(NoAuth(), AllowAll(), resolver, telemetry=False)


async def test_list_wikis_exposes_labels_and_descriptions(single: FastMCP[Any]) -> None:
    async with Client(single) as client:
        result = await client.call_tool("list_wikis", {})
    assert _data(result) == [{"id": "notes", "label": "Notes", "description": "About Notes"}]


async def test_read_edit_cycle_through_the_tools(single: FastMCP[Any]) -> None:
    async with Client(single) as client:
        rendered = _data(
            await client.call_tool("read_page", {"wiki": "notes", "path": "wiki/owner.md"})
        )
        assert rendered["content"] == "Notes page\n"
        raw = _data(
            await client.call_tool(
                "read_page", {"wiki": "notes", "path": "wiki/owner.md", "raw": True}
            )
        )
        result = _data(
            await client.call_tool(
                "write_batch",
                {
                    "wiki": "notes",
                    "message": "edit",
                    "edits": [
                        {
                            "op": "replace",
                            "path": "wiki/owner.md",
                            "old": "Notes",
                            "new": "My notes",
                            "expected_version": raw["version"],
                        }
                    ],
                },
            )
        )
        assert result["applied"] == [{"op": "replace", "path": "wiki/owner.md"}]
        hits = _data(await client.call_tool("search_wiki", {"wiki": "notes", "query": "my notes"}))
        assert hits == [{"page": "wiki/owner.md", "line": 1, "text": "My notes [[x|page]]"}]


async def test_domain_errors_reach_the_client_as_tool_errors(single: FastMCP[Any]) -> None:
    async with Client(single) as client:
        with pytest.raises(ToolError, match=r"Unknown wiki 'other'\. Known wikis: notes"):
            await client.call_tool("read_page", {"wiki": "other", "path": "index.md"})
        with pytest.raises(ToolError, match="outside the wiki root"):
            await client.call_tool("read_page", {"wiki": "notes", "path": "../x.md"})
        with pytest.raises(ToolError, match="confined"):
            await client.call_tool(
                "write_batch",
                {
                    "wiki": "notes",
                    "message": "m",
                    "edits": [{"op": "create", "path": "wiki.yaml.bak", "content": "x"}],
                },
            )


@pytest.fixture
def mapped(tmp_path: Path) -> tuple[FastMCP[Any], FakeBackend]:
    _vault(tmp_path / "tenants" / "alice", "notes", "Alice")
    _vault(tmp_path / "tenants" / "bob", "notes", "Bob")
    (tmp_path / "tenants.yaml").write_text(
        f"""\
tenants:
  alice: {{members: [{{issuer: "{ISSUER}", subject: a}}]}}
  bob: {{members: [{{issuer: "{ISSUER}", subject: b}}]}}
""",
        encoding="utf-8",
    )
    backend = FakeBackend()
    server = build_server(
        backend, AllowAuthenticated(), load_mapped_resolver(tmp_path), telemetry=False
    )
    return server, backend


@pytest.mark.parametrize(("subject", "label"), [("a", "Alice"), ("b", "Bob")])
async def test_each_caller_reads_its_own_tenant(
    mapped: tuple[FastMCP[Any], FakeBackend], subject: str, label: str
) -> None:
    server, backend = mapped
    backend.caller = Identity(ISSUER, subject)
    async with Client(server) as client:
        view = _data(
            await client.call_tool("read_page", {"wiki": "notes", "path": "wiki/owner.md"})
        )
    assert view["content"] == f"{label} page\n"


@pytest.mark.parametrize("caller", [None, Identity(ISSUER, "mallory")])
async def test_unknown_caller_cannot_even_list_tools(
    mapped: tuple[FastMCP[Any], FakeBackend], caller: Identity | None
) -> None:
    server, backend = mapped
    backend.caller = caller
    with pytest.raises(Exception, match=DENIED):
        async with Client(server) as client:
            await client.list_tools()


async def test_policy_refusal_happens_before_tenant_lookup(tmp_path: Path) -> None:
    _vault(tmp_path / "vaults", "notes", "Notes")
    backend = FakeBackend(Identity(ISSUER, "s", "intruder@example.org", True))
    server = build_server(
        backend,
        EmailAllowlist(frozenset({"reader@example.org"})),
        SingleTenantResolver(load_tenant("default", tmp_path / "vaults")),
        telemetry=False,
    )
    with pytest.raises(Exception, match=DENIED):
        async with Client(server) as client:
            await client.call_tool("list_wikis", {})


async def test_telemetry_records_names_never_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _vault(tmp_path / "vaults", "notes", "Notes")
    server = build_server(
        NoAuth(), AllowAll(), SingleTenantResolver(load_tenant("default", tmp_path / "vaults"))
    )
    async with Client(server) as client:
        await client.call_tool("search_wiki", {"wiki": "notes", "query": "confidential-term"})
    lines = [line for line in capsys.readouterr().err.splitlines() if "mindyard.telemetry" in line]
    assert len(lines) == 1
    record = json.loads(lines[0].split("mindyard.telemetry ", 1)[1])
    assert record["tool"] == "search_wiki"
    assert record["wiki"] == "notes"
    assert record["args"] == ["query", "wiki"]
    assert "confidential-term" not in lines[0]


async def test_commits_are_authored_by_a_verified_caller(tmp_path: Path) -> None:
    root = _vault(tmp_path / "vaults", "notes", "Notes")
    backend = FakeBackend()
    server = build_server(
        backend,
        AllowAll(),
        SingleTenantResolver(load_tenant("default", tmp_path / "vaults")),
        telemetry=False,
    )
    callers = [
        Identity(ISSUER, "a", "ada@example.org", True, {"name": "Ada North"}),
        Identity(ISSUER, "b", "bo@example.org", False),
    ]
    async with Client(server) as client:
        for i, caller in enumerate(callers):
            backend.caller = caller
            edits = [{"op": "create", "path": f"wiki/p{i}.md", "content": "x\n"}]
            await client.call_tool("write_batch", {"wiki": "notes", "edits": edits, "message": "m"})
    log = subprocess.run(
        ["git", "-C", str(root), "log", "-2", "--format=%an <%ae>|%cn"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    # Newest first: the unverified caller falls back to the repository identity.
    assert log == [
        "mindyard-test <test@example.invalid>|mindyard-test",
        "Ada North <ada@example.org>|mindyard-test",
    ]


async def test_lint_report_reflects_the_vault_at_the_call(
    single: FastMCP[Any], tmp_path: Path
) -> None:
    root = tmp_path / "vaults" / "notes"
    async with Client(single) as client:
        before = _data(await client.call_tool("get_lint_report", {"wiki": "notes"}))
        (root / "wiki" / "owner.md").write_text("Notes [[nowhere]]\n", encoding="utf-8")
        after = _data(await client.call_tool("get_lint_report", {"wiki": "notes"}))
        with pytest.raises(ToolError, match="notes"):
            await client.call_tool("get_lint_report", {"wiki": "elsewhere"})
    assert before.startswith("# Lint report: Notes")
    assert "nowhere" not in before
    assert "nowhere" in after  # an edit is seen at once, no report to regenerate
    assert not (root / "LINT_REPORT.md").exists()  # a read-only tool writes nothing
