"""Reading lists. Why windows: docs/adr/0003-reading-changing-data.md."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from typing import Any

from .errors import IncompleteWindowError

log = logging.getLogger("ops_client")

# fetch(resource, params) -> the parsed JSON envelope {"results": [...], "meta": {...}}
Fetch = Callable[[str, dict[str, Any]], dict]

PER_PAGE = 200
MAX_ATTEMPTS = 3


def iter_pages(fetch: Fetch, resource: str, params: dict[str, Any]) -> Iterator[dict]:
    """Yield each page's envelope until `page > page_count` (page_count comes from page 1)."""
    page = 1
    while True:
        envelope = fetch(resource, {**params, "page": page, "per_page": PER_PAGE})
        yield envelope
        if page >= envelope["meta"]["page_count"]:
            return
        page += 1


def windows(start: date, end: date, window_days: int) -> Iterator[tuple[date, date]]:
    """Consecutive inclusive windows covering start..end."""
    if window_days < 1:
        raise ValueError("window_days must be >= 1")
    if start > end:
        raise ValueError("start must not be after end")
    current = start
    while current <= end:
        last = min(current + timedelta(days=window_days - 1), end)
        yield current, last
        current = last + timedelta(days=1)


def _read_window_once(
    fetch: Fetch, resource: str, first: date, last: date
) -> tuple[dict, int, int]:
    params = {
        "created_between": f"{first.isoformat()}:{last.isoformat()}",
        "order": "created_at:asc",
    }
    by_id: dict[int, dict] = {}
    expected = -1
    pages = 0
    for envelope in iter_pages(fetch, resource, params):
        if pages == 0:
            expected = envelope["meta"]["count"]
        pages += 1
        for row in envelope["results"]:
            known = by_id.get(row["id"])
            if known is None or row["version"] > known["version"]:
                by_id[row["id"]] = row
    return by_id, expected, pages


def read_windowed(
    fetch: Fetch, resource: str, start: date, end: date, window_days: int = 7
) -> list[dict]:
    """Read every row created in start..end (inclusive), window by window.

    Per window: dedupe by id keeping the highest version, compare the unique count with the first
    page's meta.count, re-read on mismatch (3 attempts), then raise IncompleteWindowError.
    Result is sorted by id.
    """
    result: dict[int, dict] = {}
    for first, last in windows(start, end, window_days):
        for attempt in range(1, MAX_ATTEMPTS + 1):
            by_id, expected, pages = _read_window_once(fetch, resource, first, last)
            log.info(
                "window %s..%s pages=%d rows=%d expected=%d attempt=%d",
                first, last, pages, len(by_id), expected, attempt,
            )
            if len(by_id) == expected:
                break
        else:
            raise IncompleteWindowError((first.isoformat(), last.isoformat()), expected, len(by_id))
        result.update(by_id)
    return [result[key] for key in sorted(result)]


def naive_read_by_updated_at(fetch: Fetch, resource: str) -> list[dict]:
    """DO NOT USE for real extracts. Offset paging ordered by `updated_at`, with no checks.

    It exists only to demonstrate the failure in ADR 0003: when rows are edited while you page,
    they jump to the end of the ordering, the rows behind them slide up, and some rows are
    silently skipped.
    """
    rows: list[dict] = []
    for envelope in iter_pages(fetch, resource, {"order": "updated_at:asc"}):
        rows.extend(envelope["results"])
    return rows

