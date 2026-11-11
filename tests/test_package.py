# SPDX-License-Identifier: AGPL-3.0-or-later
import json
from pathlib import Path

import mindyard

ROOT = Path(__file__).resolve().parents[1]


def test_version_is_exposed() -> None:
    assert mindyard.__version__


def test_registry_entry_matches_the_package() -> None:
    entry = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    assert entry["version"] == mindyard.__version__
    assert [p["version"] for p in entry["packages"]] == [mindyard.__version__]
    # The MCP registry proves PyPI ownership by finding this line in the published README.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"<!-- mcp-name: {entry['name']} -->" in readme
