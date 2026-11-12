"""Read and validate a changeset CSV (ADR 0004). Every problem is collected, then raised together.

Money in the file is dollars; here it becomes integer cents through `Decimal`. A value with
more than 2 decimals is an error, never rounded.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

COLUMNS = ("code", "name", "status", "budget_dollars", "end_date")
STATUSES = ("active", "on_hold", "closed")
NULL_TEXT = "NULL"

# File column -> API field. Only `budget_dollars` is renamed (and converted).
FIELD_OF_COLUMN = {
    "name": "name",
    "status": "status",
    "budget_dollars": "budget_cents",
    "end_date": "end_date",
}

_MONEY = re.compile(r"^(\d+|\d{1,3}(,\d{3})+)(\.\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Problem:
    line: int  # 1-based file line, header = 1
    column: str
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}"
        if self.column:
            where += f", {self.column}"
        return f"{where}: {self.message}"


class ChangesetError(Exception):
    """The file has one or more problems. `problems` lists all of them."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = list(problems)
        count = len(self.problems)
        lines = "\n".join(f"  {p}" for p in self.problems)
        super().__init__(f"{count} problem{'s' if count != 1 else ''} in the changeset:\n{lines}")


@dataclass(frozen=True)
class Desired:
    """One wanted row. `values` holds only the fields to change, keyed by API field name."""

    code: str
    line: int
    values: dict[str, object] = field(default_factory=dict)


# -- value parsers (raise ValueError with the message the user sees) -------------------------------


def parse_dollars(text: str) -> int:
    """`12,500.50` -> 1250050. Plain or comma-grouped, 0 or more, at most 2 decimals."""
    if text.startswith("-"):
        raise ValueError("must be 0 or more")
    if not _MONEY.match(text):
        raise ValueError("not a dollar amount (use 1234.50 or 1,234.50)")
    plain = text.replace(",", "")
    _, _, decimals = plain.partition(".")
    if len(decimals) > 2:
        raise ValueError("more than 2 decimals; cents are not rounded")
    return int(Decimal(plain) * 100)


def _parse_status(text: str) -> str:
    if text not in STATUSES:
        raise ValueError(f"must be one of {', '.join(STATUSES)}")
    return text


def _parse_end_date(text: str) -> str | None:
    if text.upper() == NULL_TEXT:
        return None
    if not _DATE.match(text):
        raise ValueError("must be YYYY-MM-DD or NULL")
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ValueError("not a real calendar date") from None
    return text


def _parse_name(text: str) -> str:
    return text


_PARSERS = {
    "name": _parse_name,
    "status": _parse_status,
    "budget_dollars": parse_dollars,
    "end_date": _parse_end_date,
}


# -- file -----------------------------------------------------------------------------------------


def file_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_changeset(
    path: str | Path, known_codes: Collection[str] | None = None
) -> list[Desired]:
    """Read `path`. With `known_codes`, a code not in it is a problem too."""
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ChangesetError([Problem(1, "", "file is not valid UTF-8")]) from None
    return parse_text(text, known_codes)


def parse_text(text: str, known_codes: Collection[str] | None = None) -> list[Desired]:
    problems: list[Problem] = []
    reader = csv.reader(io.StringIO(text, newline=""))
    header = [h.strip() for h in next(reader, [])]
    if not header:
        raise ChangesetError([Problem(1, "", "file is empty")])

    seen_columns: set[str] = set()
    for name in header:
        if name not in COLUMNS:
            problems.append(
                Problem(1, name, f"unknown column; allowed: {', '.join(COLUMNS)}")
            )
        elif name in seen_columns:
            problems.append(Problem(1, name, "column appears twice"))
        seen_columns.add(name)
    if "code" not in header:
        problems.append(Problem(1, "code", "missing required column 'code'"))
        raise ChangesetError(problems)

    desired: list[Desired] = []
    first_line: dict[str, int] = {}
    previous_end = reader.line_num
    for cells in reader:
        line = previous_end + 1
        previous_end = reader.line_num
        if not any(c.strip() for c in cells):
            continue
        if len(cells) != len(header):
            problems.append(
                Problem(line, "", f"expected {len(header)} cells, found {len(cells)}")
            )
            continue
        row = dict(zip(header, (c.strip() for c in cells), strict=True))

        code = row["code"]
        if not code:
            problems.append(Problem(line, "code", "code is empty"))
            continue
        if code in first_line:
            problems.append(
                Problem(line, "code", f"duplicate code {code} (first on line {first_line[code]})")
            )
            continue
        first_line[code] = line
        if known_codes is not None and code not in known_codes:
            problems.append(Problem(line, "code", f"unknown code {code}"))

        values: dict[str, object] = {}
        for column, parser in _PARSERS.items():
            cell = row.get(column, "")
            if not cell:
                continue  # blank = no change
            try:
                values[FIELD_OF_COLUMN[column]] = parser(cell)
            except ValueError as exc:
                problems.append(Problem(line, column, f"{cell!r}: {exc}"))
        desired.append(Desired(code, line, values))

    if not first_line and not problems:
        problems.append(Problem(1, "", "file has no data rows"))
    if problems:
        raise ChangesetError(problems)
    return desired
