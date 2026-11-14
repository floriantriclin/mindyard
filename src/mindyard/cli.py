# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ``mindyard`` command line: init, serve, lint, token."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path

from mindyard import __version__


def _cmd_init(args: argparse.Namespace) -> int:
    from mindyard.init import InitError, init_vault

    target = Path(args.directory)
    label = args.label or target.name.replace("-", " ").capitalize()
    try:
        init_vault(target, label, "demo" if args.demo else "blank")
    except InitError as exc:
        print(f"mindyard init: {exc}", file=sys.stderr)
        return 2
    print(f"Vault created in {target}. Edit wiki.yaml and schema.md to make it yours.")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from mindyard.mcp import run
    from mindyard.settings import Settings, SettingsError
    from mindyard.tenancy import TenantConfigError

    env = dict(os.environ)
    for flag, name in (
        ("data_root", "MINDYARD_DATA_ROOT"),
        ("host", "MINDYARD_HOST"),
        ("port", "MINDYARD_PORT"),
    ):
        value = getattr(args, flag)
        if value is not None:
            env[name] = str(value)
    try:
        run(Settings.from_env(env), "stdio" if args.stdio else "http")
    except (SettingsError, TenantConfigError) as exc:
        print(f"mindyard serve: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    from mindyard.core.config import CONFIG_FILE
    from mindyard.lint import fix_table_pipes, lint_wiki, write_report
    from mindyard.schema import ManifestError, Wiki, load_manifest

    root = Path(args.vault).resolve()
    if not (root / CONFIG_FILE).is_file():
        print(f"mindyard lint: no {CONFIG_FILE} in {root}", file=sys.stderr)
        return 2
    try:
        manifest = load_manifest(root)
    except ManifestError as exc:
        print(f"mindyard lint: {exc}", file=sys.stderr)
        return 2
    wiki = Wiki(manifest.to_config(root.name, root), manifest)
    if args.fix:
        for page, count in fix_table_pipes(wiki):
            print(f"fixed {count} table pipe(s) in {page}")
    findings = lint_wiki(wiki)
    report = write_report(wiki, findings)
    print(f"{findings.total} issue(s), {len(findings.items) - findings.total} notice(s): {report}")
    return 1 if findings.total else 0


def _cmd_token(args: argparse.Namespace) -> int:
    from mindyard.auth import TokenStoreError, add_token

    data_root = args.data_root or os.environ.get("MINDYARD_DATA_ROOT")
    if not data_root:
        print("mindyard token: set MINDYARD_DATA_ROOT or pass --data-root", file=sys.stderr)
        return 2
    try:
        token = add_token(Path(data_root) / "tokens.yaml", args.name)
    except TokenStoreError as exc:
        print(f"mindyard token: {exc}", file=sys.stderr)
        return 2
    print(token)
    print(
        "Shown once: only its digest is stored. Restart the server to load it.",
        file=sys.stderr,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mindyard", description=__doc__)
    parser.add_argument("--version", action="version", version=f"mindyard {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create a vault")
    p.add_argument("directory")
    p.add_argument("--label", help="display name (default: from the directory name)")
    p.add_argument("--demo", action="store_true", help="start from the demo garden vault")
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("serve", help="run the MCP server (configured by MINDYARD_* variables)")
    p.add_argument("--data-root")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument(
        "--stdio",
        action="store_true",
        help="serve over stdin/stdout for a local client (no auth, ignores host and port)",
    )
    p.set_defaults(func=_cmd_serve)

    p = sub.add_parser("lint", help="lint one vault and write its LINT_REPORT.md")
    p.add_argument("vault")
    p.add_argument("--fix", action="store_true", help="escape table-cell wikilink pipes first")
    p.set_defaults(func=_cmd_lint)

    p = sub.add_parser("token", help="mint a bearer token")
    p.add_argument("action", choices=["new"])
    p.add_argument("name", help="principal name, e.g. laptop")
    p.add_argument("--data-root")
    p.set_defaults(func=_cmd_token)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # A dependency of FastMCP's OAuth support announces a future change on import;
    # it says nothing about mindyard and alarms people reading the server log.
    # authlib installs an "always" filter when loaded, so load it first.
    with contextlib.suppress(ImportError):
        import authlib.deprecate  # type: ignore[import-untyped]  # noqa: F401
    warnings.filterwarnings("ignore", message="The httpx module is deprecated")
    args = build_parser().parse_args(argv)
    code: int = args.func(args)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
