# SPDX-License-Identifier: AGPL-3.0-or-later
"""``wiki.yaml``: the machine-readable contract of a vault.

Two files describe a wiki, with distinct authority:

- ``wiki.yaml`` is enforced. The server reads its layout, the linter applies its
  rules. It is outside the write zones, so the model cannot loosen it.
- ``schema.md`` is advisory prose for the model: domain, conventions, examples.

Validation is strict (unknown keys are errors) because a typo in a rule must not
silently disable it. Every error names the file and the offending field.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from mindyard.core.config import CONFIG_FILE, WikiConfig

WIKI_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,62}$"
_WIKI_ID_RE = re.compile(WIKI_ID_PATTERN)


class ManifestError(ValueError):
    """A ``wiki.yaml`` that cannot be loaded; the message is operator-facing."""


def _relative_path(value: str) -> str:
    """Reject absolute paths, parent references and empty names."""
    p = PurePosixPath(value)
    if not value.strip() or p.is_absolute() or ".." in p.parts or "\\" in value:
        raise ValueError(f"must be a relative path inside the vault, got {value!r}")
    return p.as_posix()


RelPath = Annotated[str, Field(min_length=1)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Layout(_Strict):
    wiki_dir: RelPath = "wiki"
    raw_dir: RelPath = "raw"
    index: RelPath = "index.md"
    log: RelPath = "log.md"
    schema_: RelPath = Field("schema.md", alias="schema")
    lint_report: RelPath = "LINT_REPORT.md"

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @field_validator("*")
    @classmethod
    def _inside_vault(cls, value: str) -> str:
        return _relative_path(value)


class LogSettings(_Strict):
    sentinel: str = Field("<!-- log-end -->", min_length=1)
    timestamp: str = "%Y-%m-%d"


class DateDerivedStatus(_Strict):
    """Status implied by a page's own dates, as of the lint run.

    A stored state that dates can imply rots by itself as time passes; the
    linter flags pages whose stored ``status`` disagrees with their dates.
    """

    start: str = "start_date"
    end: str | None = "end_date"
    upcoming: str = "upcoming"
    ongoing: str = "ongoing"
    past: str = "past"


class EntityKind(_Strict):
    """Frontmatter contract for pages whose ``entity_kind`` is this kind."""

    required: list[str] = []
    status: list[str] | None = None
    status_from_dates: DateDerivedStatus | None = None

    @model_validator(mode="after")
    def _derived_values_are_allowed(self) -> EntityKind:
        derived = self.status_from_dates
        if derived is None:
            return self
        if self.status is None:
            raise ValueError("status_from_dates requires a closed 'status' list")
        missing = {derived.upcoming, derived.ongoing, derived.past} - set(self.status)
        if missing:
            raise ValueError(
                f"status_from_dates values not in 'status': {sorted(missing)}. Add them to "
                "'status', or name the derived statuses with the words 'status' already "
                "uses: status_from_dates: {start: ..., end: ..., upcoming: <word>, "
                "ongoing: <word>, past: <word>}"
            )
        return self


class OrphanRule(_Strict):
    exempt: list[str] = []


class LintSettings(_Strict):
    orphans: OrphanRule = OrphanRule()
    index_entry_max_chars: int | None = Field(250, ge=1)
    ignored_dirs: list[str] = [".git", ".obsidian"]


class WikiManifest(_Strict):
    mindyard: Literal[1]
    id: str | None = None
    label: str = Field(min_length=1)
    description: str = ""
    layout: Layout = Layout()
    log: LogSettings = LogSettings()
    entities: dict[str, EntityKind] = {}
    lint: LintSettings = LintSettings()

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str | None) -> str | None:
        if value is not None and not _WIKI_ID_RE.match(value):
            raise ValueError(f"must match {WIKI_ID_PATTERN}")
        return value

    def to_config(self, wiki_id: str, root: Path) -> WikiConfig:
        """The core's view of this wiki, rooted at ``root``."""
        return WikiConfig(
            id=wiki_id,
            root=root,
            label=self.label,
            description=self.description,
            wiki_dir=self.layout.wiki_dir,
            raw_dir=self.layout.raw_dir,
            index_file=self.layout.index,
            log_file=self.layout.log,
            schema_file=self.layout.schema_,
            lint_report_file=self.layout.lint_report,
            log_sentinel=self.log.sentinel,
        )


def _format_errors(source: str, exc: ValidationError) -> str:
    lines = [f"{source}: invalid configuration"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "(root)"
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def parse_manifest(text: str, source: str, dir_name: str) -> WikiManifest:
    """Parse and validate the text of a ``wiki.yaml``; ``source`` names it in errors.

    The wiki id is the directory name. An ``id`` key, if present, must agree with
    it, so a copied vault can never impersonate another one by its id.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestError(f"{source}: not valid YAML ({exc})") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"{source}: must be a YAML mapping")
    try:
        manifest = WikiManifest.model_validate(data)
    except ValidationError as exc:
        raise ManifestError(_format_errors(source, exc)) from exc
    if not _WIKI_ID_RE.match(dir_name):
        raise ManifestError(f"{source}: directory name {dir_name!r} is not a valid wiki id")
    if manifest.id is not None and manifest.id != dir_name:
        raise ManifestError(
            f"{source}: id {manifest.id!r} does not match its directory {dir_name!r}"
        )
    return manifest


def load_manifest(root: Path) -> WikiManifest:
    """Parse and validate ``<root>/wiki.yaml``."""
    source = root / CONFIG_FILE
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestError(f"{source}: cannot read ({exc.strerror})") from exc
    return parse_manifest(text, str(source), root.name)


def check_definition(current: str, proposed: str, dir_name: str) -> WikiManifest:
    """Validate a one-time definition of ``wiki.yaml`` written by the model.

    The proposed text must be a valid manifest, and it may not move the vault's
    structure: ``layout`` (where the write zones are) and ``log`` (its sentinel)
    stay as they are. Errors name the file, never a server path.
    """
    before = parse_manifest(current, CONFIG_FILE, dir_name)
    after = parse_manifest(proposed, CONFIG_FILE, dir_name)
    for key in ("layout", "log"):
        if getattr(after, key) != getattr(before, key):
            raise ManifestError(
                f"{CONFIG_FILE}: '{key}' cannot change in a definition by the model"
            )
    return after
