"""Validation helpers for Chronos scheduler inputs and outputs."""
from __future__ import annotations

from typing import Any, Dict

from .io_schema import SchedulerInput, SchedulerOutput


def validate_input(payload: Dict[str, Any] | SchedulerInput) -> SchedulerInput:
    """Validate raw JSON payload into a :class:`SchedulerInput`."""

    if isinstance(payload, SchedulerInput):
        return payload
    return SchedulerInput.parse_obj(payload)


def validate_output(result: Dict[str, Any] | SchedulerOutput) -> SchedulerOutput:
    """Validate raw solver output into a :class:`SchedulerOutput`."""

    if isinstance(result, SchedulerOutput):
        return result
    return SchedulerOutput.parse_obj(result)
