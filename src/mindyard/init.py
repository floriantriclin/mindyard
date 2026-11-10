# SPDX-License-Identifier: AGPL-3.0-or-later
"""``mindyard init``: create a vault from a packaged template, as a git repo."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from importlib import resources
from pathlib import Path
from string import Template

from mindyard.core.git import commit_files
from mindyard.schema import load_manifest

TEMPLATES = ("blank", "demo")
# Only these files carry placeholders; everything else is copied verbatim.
_SUBSTITUTED = ("wiki.yaml", "log.md")


class InitError(ValueError):
    pass


def init_vault(target: Path, label: str, template: str = "blank") -> Path:
    """Create ``target`` from ``template``, ``git init`` it, commit, validate."""
    if template not in TEMPLATES:
        raise InitError(f"unknown template {template!r} (choose from {', '.join(TEMPLATES)})")
    if target.exists() and any(target.iterdir()):
        raise InitError(f"{target} already exists and is not empty")
    source = resources.files("mindyard") / "templates" / template
    with resources.as_file(source) as src:
        shutil.copytree(src, target, dirs_exist_ok=True)
    values = {"label": label.replace('"', "'"), "date": date.today().isoformat()}
    for name in _SUBSTITUTED:
        path = target / name
        path.write_text(Template(path.read_text(encoding="utf-8")).substitute(values), "utf-8")
    load_manifest(target)  # a template that does not validate is a bug, fail loudly
    subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
    files = sorted(
        p.relative_to(target).as_posix()
        for p in target.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(target).parts
    )
    commit_files(target, files, f"Initialise vault from the '{template}' template")
    return target
