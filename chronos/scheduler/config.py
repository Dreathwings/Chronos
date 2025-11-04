"""Configuration defaults for the Chronos scheduler."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class SolverConfig:
    """Configuration controlling the CP-SAT solver."""

    time_limit_seconds: int = 30
    random_seed: int | None = 1
    num_search_workers: int = 0
    max_solutions: int = 1


@dataclass
class ObjectiveWeights:
    """Weights used when building the optimisation objective."""

    teacher_compactness: int = 1
    group_compactness: int = 1
    early_slot_penalty: int = 1
    late_slot_penalty: int = 1
    room_change_penalty: int = 1
    teacher_overload_penalty: int = 5
    group_overload_penalty: int = 5
    preference_miss_penalty: int = 2

    def as_dict(self) -> Dict[str, int]:
        return {
            "teacher_compactness": self.teacher_compactness,
            "group_compactness": self.group_compactness,
            "early_slot_penalty": self.early_slot_penalty,
            "late_slot_penalty": self.late_slot_penalty,
            "room_change_penalty": self.room_change_penalty,
            "teacher_overload_penalty": self.teacher_overload_penalty,
            "group_overload_penalty": self.group_overload_penalty,
            "preference_miss_penalty": self.preference_miss_penalty,
        }


@dataclass
class SchedulerConfig:
    """Top level configuration for the scheduler module."""

    solver: SolverConfig = field(default_factory=SolverConfig)
    weights: ObjectiveWeights = field(default_factory=ObjectiveWeights)
    enable_soft_limits_as_hard: bool = False


DEFAULT_CONFIG = SchedulerConfig()
"""Default configuration used by :mod:`chronos.scheduler`."""
