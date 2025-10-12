from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Iterable, List, Tuple


DATE_FORMAT = "%Y-%m-%d"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        return None


def parse_unavailability_ranges(raw: str | None) -> List[Tuple[date, date]]:
    """Parse stored teacher unavailability information into date ranges.

    The stored format supports either a JSON array of objects with ``start`` and
    ``end`` keys or the legacy comma separated list of ISO formatted dates. The
    returned ranges are normalised so that the start is not later than the end
    and overlapping periods are merged for easier processing downstream.
    """

    if not raw:
        return []

    ranges: list[tuple[date, date]] = []

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = None

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            start = _parse_date(item.get("start"))
            end = _parse_date(item.get("end")) or start
            if start is None or end is None:
                continue
            if end < start:
                start, end = end, start
            ranges.append((start, end))
    else:
        tokens = raw.replace("\n", ",").split(",")
        for token in tokens:
            day = _parse_date(token.strip())
            if day is None:
                continue
            ranges.append((day, day))

    if not ranges:
        return []

    ranges.sort(key=lambda value: (value[0], value[1]))
    merged: list[tuple[date, date]] = []
    for current_start, current_end in ranges:
        if not merged:
            merged.append((current_start, current_end))
            continue
        previous_start, previous_end = merged[-1]
        if current_start <= previous_end + timedelta(days=1):
            merged[-1] = (previous_start, max(previous_end, current_end))
        else:
            merged.append((current_start, current_end))
    return merged


def serialise_unavailability_ranges(ranges: Iterable[tuple[date, date]]) -> str | None:
    normalised: list[dict[str, str]] = []
    for start, end in ranges:
        normalised.append({"start": start.isoformat(), "end": end.isoformat()})
    if not normalised:
        return None
    return json.dumps(normalised, ensure_ascii=False)


def ranges_as_payload(ranges: Iterable[tuple[date, date]]) -> list[dict[str, str]]:
    return [{"start": start.isoformat(), "end": end.isoformat()} for start, end in ranges]
