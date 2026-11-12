"""Plan a changeset against live data (ADR 0004 step 3). Pure data; views render it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ops_client import OpsClient, Project

from .changeset import ChangesetError, Desired, Problem, file_sha256, parse_changeset

RESOURCE = "projects"


@dataclass(frozen=True)
class FieldChange:
    field: str
    old: object
    new: object


@dataclass(frozen=True)
class RowChange:
    """One project with at least one field to change. `version` is the one read at plan time."""

    row_id: int
    code: str
    version: int
    fields: tuple[FieldChange, ...]


@dataclass(frozen=True)
class Unchanged:
    row_id: int
    code: str
    version: int


@dataclass(frozen=True)
class Plan:
    changes: tuple[RowChange, ...]
    no_change: tuple[Unchanged, ...]


def build_plan(client: OpsClient, desired: Sequence[Desired]) -> Plan:
    """Read the target rows now; keep only the fields whose value differs."""
    by_code: dict[str, Project] = {p.code: p for p in client.list(RESOURCE)}  # type: ignore[attr-defined]
    missing = [
        Problem(d.line, "code", f"unknown code {d.code}") for d in desired if d.code not in by_code
    ]
    if missing:
        raise ChangesetError(missing)

    changes: list[RowChange] = []
    no_change: list[Unchanged] = []
    for d in desired:
        current = by_code[d.code]
        fields = tuple(
            FieldChange(name, getattr(current, name), new)
            for name, new in d.values.items()
            if getattr(current, name) != new
        )
        if fields:
            changes.append(RowChange(current.id, current.code, current.version, fields))
        else:
            no_change.append(Unchanged(current.id, current.code, current.version))
    return Plan(tuple(changes), tuple(no_change))


def plan_from_file(client: OpsClient, path: str | Path) -> tuple[Plan, str]:
    """Validate the file (codes checked against the API), then plan. Returns (plan, sha256)."""
    known = {p.code for p in client.list(RESOURCE)}  # type: ignore[attr-defined]
    desired = parse_changeset(path, known)
    return build_plan(client, desired), file_sha256(path)
