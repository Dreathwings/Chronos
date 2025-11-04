"""JSON schema definitions for the scheduler inputs and outputs."""
from __future__ import annotations

from datetime import date, time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator


class TimeSlotModel(BaseModel):
    slot_id: str = Field(..., description="Unique identifier for the slot")
    day: date
    start: time
    end: time

    @validator("end")
    def validate_end(cls, value: time, values: Dict[str, time]):  # noqa: N805
        start = values.get("start")
        if start and value <= start:
            raise ValueError("End time must be strictly after start time")
        return value


class TeacherCapability(BaseModel):
    module_id: str
    types: List[Literal["CM", "TD", "TP"]]


class TeacherModel(BaseModel):
    teacher_id: str
    name: str
    can_teach: List[TeacherCapability]
    availability: List[str]
    hard_unavailability: List[str] = Field(default_factory=list)
    max_per_day: Optional[int] = None
    max_per_week: Optional[int] = None
    min_per_day: Optional[int] = None
    preferred_slots: List[str] = Field(default_factory=list)
    disliked_slots: List[str] = Field(default_factory=list)


class GroupModel(BaseModel):
    group_id: str
    name: str
    size: int
    incompatible_with: List[str] = Field(default_factory=list)


class RoomModel(BaseModel):
    room_id: str
    name: str
    capacity: int
    equipment: List[str] = Field(default_factory=list)


class CourseModel(BaseModel):
    course_id: str
    module_id: str
    type: Literal["CM", "TD", "TP"]
    duration_minutes: int
    total_units: int
    groups: List[str]
    allowed_time_slots: Optional[List[str]] = None
    precedence: List[str] = Field(default_factory=list)
    preferred_slots: List[str] = Field(default_factory=list)
    forbidden_slots: List[str] = Field(default_factory=list)
    required_equipment: List[str] = Field(default_factory=list)

    @validator("duration_minutes")
    def validate_duration(cls, value: int):  # noqa: N805
        if value <= 0:
            raise ValueError("duration_minutes must be strictly positive")
        if value % 30 != 0:
            raise ValueError("duration_minutes must be a multiple of 30")
        return value

    @validator("total_units")
    def validate_units(cls, value: int):  # noqa: N805
        if value <= 0:
            raise ValueError("total_units must be greater than zero")
        return value


class GlobalRulesModel(BaseModel):
    forbidden_slots: List[str] = Field(default_factory=list)
    lunch_start: Optional[time] = None
    lunch_end: Optional[time] = None
    lunch_break_minutes: int = 60
    daily_amplitude_minutes: Optional[int] = None

    @validator("lunch_break_minutes")
    def validate_break(cls, value: int):  # noqa: N805
        if value < 0:
            raise ValueError("lunch_break_minutes must be non negative")
        return value


class ObjectiveWeightsModel(BaseModel):
    teacher_compactness: int = 1
    group_compactness: int = 1
    early_slot_penalty: int = 1
    late_slot_penalty: int = 1
    room_change_penalty: int = 1
    teacher_overload_penalty: int = 5
    group_overload_penalty: int = 5
    preference_miss_penalty: int = 2


class SolverLimitsModel(BaseModel):
    time_limit_seconds: int = 30
    random_seed: Optional[int] = 1
    num_solutions: int = 1
    num_search_workers: int = 0


class SchedulerInput(BaseModel):
    time_grid: List[TimeSlotModel]
    teachers: List[TeacherModel]
    groups: List[GroupModel]
    rooms: List[RoomModel]
    courses: List[CourseModel]
    global_rules: GlobalRulesModel = Field(default_factory=GlobalRulesModel)
    weights: ObjectiveWeightsModel = Field(default_factory=ObjectiveWeightsModel)
    limits: SolverLimitsModel = Field(default_factory=SolverLimitsModel)

    @validator("time_grid")
    def validate_slots_unique(cls, value: List[TimeSlotModel]):  # noqa: N805
        identifiers = {slot.slot_id for slot in value}
        if len(identifiers) != len(value):
            raise ValueError("time_grid slot_id must be unique")
        return value


class SessionResult(BaseModel):
    session_id: str
    course_id: str
    type: Literal["CM", "TD", "TP"]
    teacher_id: str
    group_id: str
    room_id: str
    date: date
    start: time
    end: time


class SchedulerOutput(BaseModel):
    sessions: List[SessionResult]
    metrics: Dict[str, Any]
