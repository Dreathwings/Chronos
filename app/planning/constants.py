from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable

# Working windows respecting pauses
WORKING_WINDOWS: list[tuple[time, time]] = [
    (time(8, 0), time(10, 0)),
    (time(10, 15), time(12, 15)),
    (time(13, 30), time(15, 30)),
    (time(15, 45), time(17, 45)),
]

SCHEDULE_SLOTS: list[tuple[time, time]] = [
    (time(8, 0), time(9, 0)),
    (time(9, 0), time(10, 0)),
    (time(10, 15), time(11, 15)),
    (time(11, 15), time(12, 15)),
    (time(13, 30), time(14, 30)),
    (time(14, 30), time(15, 30)),
    (time(15, 45), time(16, 45)),
    (time(16, 45), time(17, 45)),
]

MAX_SLOT_GAP = timedelta(minutes=15)


def _build_extended_breaks() -> set[tuple[time, time]]:
    extended: set[tuple[time, time]] = set()
    for idx in range(len(WORKING_WINDOWS) - 1):
        _, current_end = WORKING_WINDOWS[idx]
        next_start, _ = WORKING_WINDOWS[idx + 1]
        gap = datetime.combine(date.min, next_start) - datetime.combine(
            date.min, current_end
        )
        if gap > MAX_SLOT_GAP:
            extended.add((current_end, next_start))
    return extended


EXTENDED_BREAKS = _build_extended_breaks()

START_TIMES: list[time] = [slot_start for slot_start, _ in SCHEDULE_SLOTS]


def fits_in_windows(start: time, end: time) -> bool:
    for window_start, window_end in WORKING_WINDOWS:
        if window_start <= start and end <= window_end:
            return True
    return False


def collect_contiguous_slots(
    start_index: int, length: int
) -> list[tuple[time, time]] | None:
    slots: list[tuple[time, time]] = []
    previous_end: time | None = None
    for offset in range(length):
        index = start_index + offset
        if index >= len(SCHEDULE_SLOTS):
            return None
        slot_start, slot_end = SCHEDULE_SLOTS[index]
        if previous_end:
            gap = datetime.combine(date.min, slot_start) - datetime.combine(
                date.min, previous_end
            )
            if gap < timedelta(0):
                return None
            if gap > MAX_SLOT_GAP and (previous_end, slot_start) not in EXTENDED_BREAKS:
                return None
        slots.append((slot_start, slot_end))
        previous_end = slot_end
    return slots


def slot_range_for_segments(
    day: date, segment_lengths: Iterable[int], start_index: int
) -> list[tuple[datetime, datetime]] | None:
    segment_count = sum(segment_lengths)
    contiguous = collect_contiguous_slots(start_index, segment_count)
    if not contiguous:
        return None
    if not all(fits_in_windows(start, end) for start, end in contiguous):
        return None
    segments: list[tuple[datetime, datetime]] = []
    index = 0
    lengths = list(segment_lengths)
    for length in lengths:
        segment_start = contiguous[index][0]
        segment_end = contiguous[index + length - 1][1]
        segments.append(
            (
                datetime.combine(day, segment_start),
                datetime.combine(day, segment_end),
            )
        )
        index += length
    return segments
