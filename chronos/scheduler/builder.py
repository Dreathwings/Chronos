"""CP-SAT model construction for the Chronos scheduler."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, time
from typing import Dict, List, Sequence, Tuple

from ortools.sat.python import cp_model

from .config import SchedulerConfig
from .io_schema import SchedulerInput
from .model import (
    Course,
    GlobalRules,
    Group,
    Room,
    Session,
    Teacher,
    TimeSlot,
    minutes_between,
)


@dataclass(frozen=True)
class SessionOption:
    """Represents a feasible placement for a session."""

    option_id: str
    slot_ids: Tuple[str, ...]
    day: date
    start: time
    end: time


@dataclass
class SchedulerModel:
    """Container bundling the CP-SAT model with auxiliary data."""

    model: cp_model.CpModel
    sessions: List[Session]
    time_slots: Dict[str, TimeSlot]
    teachers: Dict[str, Teacher]
    rooms: Dict[str, Room]
    groups: Dict[str, Group]
    courses: Dict[str, Course]
    global_rules: GlobalRules
    session_options: Dict[str, List[SessionOption]]
    variables: Dict[str, Dict]


class ModelBuilder:
    """Translate validated inputs into a constraint programming model."""

    def __init__(self, data: SchedulerInput, config: SchedulerConfig):
        self.data = data
        self.config = config
        self.model = cp_model.CpModel()
        self.sessions: List[Session] = []
        self.session_options: Dict[str, List[SessionOption]] = {}
        self.variables: Dict[str, Dict] = defaultdict(dict)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def build(self) -> SchedulerModel:
        time_slots = self._build_time_slots()
        teachers = self._build_teachers()
        rooms = self._build_rooms()
        groups = self._build_groups()
        courses = self._build_courses()
        global_rules = self._build_global_rules()

        self._create_sessions(courses)
        self._create_session_options(time_slots, courses, global_rules)
        self._create_assignment_variables(teachers, rooms, groups, courses)
        self._add_teacher_constraints(teachers)
        self._add_group_constraints(groups)
        self._add_room_constraints(rooms)
        self._add_precedence_constraints(courses)
        self._add_calendar_constraints(teachers, groups, global_rules)

        return SchedulerModel(
            model=self.model,
            sessions=self.sessions,
            time_slots=time_slots,
            teachers=teachers,
            rooms=rooms,
            groups=groups,
            courses=courses,
            global_rules=global_rules,
            session_options=self.session_options,
            variables=self.variables,
        )

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    def _build_time_slots(self) -> Dict[str, TimeSlot]:
        ordered = sorted(self.data.time_grid, key=lambda slot: (slot.day, slot.start))
        slots: Dict[str, TimeSlot] = {}
        for slot in ordered:
            slots[slot.slot_id] = TimeSlot(
                slot_id=slot.slot_id,
                day=slot.day,
                start=slot.start,
                end=slot.end,
            )
        return slots

    def _build_teachers(self) -> Dict[str, Teacher]:
        teachers: Dict[str, Teacher] = {}
        for teacher in self.data.teachers:
            capability_map: Dict[str, Sequence[str]] = defaultdict(list)
            for capability in teacher.can_teach:
                capability_map.setdefault(capability.module_id, [])
                capability_map[capability.module_id] = list(
                    sorted(set(capability_map[capability.module_id]) | set(capability.types))
                )
            teachers[teacher.teacher_id] = Teacher(
                teacher_id=teacher.teacher_id,
                name=teacher.name,
                can_teach=dict(capability_map),
                availability=set(teacher.availability),
                hard_unavailability=set(teacher.hard_unavailability),
                max_per_day=teacher.max_per_day,
                max_per_week=teacher.max_per_week,
                min_per_day=teacher.min_per_day,
                preferred_slots=set(teacher.preferred_slots),
                disliked_slots=set(teacher.disliked_slots),
            )
        return teachers

    def _build_groups(self) -> Dict[str, Group]:
        groups: Dict[str, Group] = {}
        for group in self.data.groups:
            groups[group.group_id] = Group(
                group_id=group.group_id,
                name=group.name,
                size=group.size,
                incompatible_with=set(group.incompatible_with),
            )
        return groups

    def _build_rooms(self) -> Dict[str, Room]:
        rooms: Dict[str, Room] = {}
        for room in self.data.rooms:
            rooms[room.room_id] = Room(
                room_id=room.room_id,
                name=room.name,
                capacity=room.capacity,
                equipment=set(room.equipment),
            )
        return rooms

    def _build_courses(self) -> Dict[str, Course]:
        courses: Dict[str, Course] = {}
        for course in self.data.courses:
            courses[course.course_id] = Course(
                course_id=course.course_id,
                module_id=course.module_id,
                type=course.type,
                duration_minutes=course.duration_minutes,
                total_units=course.total_units,
                groups=list(course.groups),
                allowed_time_slots=set(course.allowed_time_slots or []),
                precedence=list(course.precedence),
                preferred_slots=set(course.preferred_slots),
                forbidden_slots=set(course.forbidden_slots),
                required_equipment=set(course.required_equipment),
            )
        return courses

    def _build_global_rules(self) -> GlobalRules:
        rules = self.data.global_rules
        return GlobalRules(
            forbidden_slots=set(rules.forbidden_slots),
            lunch_start=rules.lunch_start,
            lunch_end=rules.lunch_end,
            lunch_break_minutes=rules.lunch_break_minutes,
            daily_amplitude_minutes=rules.daily_amplitude_minutes,
        )

    # ------------------------------------------------------------------
    # Session preparation
    # ------------------------------------------------------------------
    def _create_sessions(self, courses: Dict[str, Course]) -> None:
        for course in courses.values():
            for index in range(course.total_units):
                self.sessions.append(
                    Session(
                        session_id=f"{course.course_id}#{index}",
                        course_id=course.course_id,
                        module_id=course.module_id,
                        type=course.type,
                        groups=course.groups,
                        duration_minutes=course.duration_minutes,
                    )
                )

    def _create_session_options(
        self,
        slots: Dict[str, TimeSlot],
        courses: Dict[str, Course],
        rules: GlobalRules,
    ) -> None:
        ordered_slots = list(slots.values())
        for session in self.sessions:
            course = courses[session.course_id]
            options: List[SessionOption] = []
            for index in range(len(ordered_slots)):
                candidate = self._collect_contiguous_slots(ordered_slots, index, session.duration_minutes)
                if not candidate:
                    continue
                slot_ids = tuple(slot.slot_id for slot in candidate)
                if course.allowed_time_slots and not set(slot_ids).issubset(course.allowed_time_slots):
                    continue
                if any(slot_id in course.forbidden_slots for slot_id in slot_ids):
                    continue
                if any(slot_id in rules.forbidden_slots for slot_id in slot_ids):
                    continue
                options.append(
                    SessionOption(
                        option_id=f"{session.session_id}@{candidate[0].slot_id}",
                        slot_ids=slot_ids,
                        day=candidate[0].day,
                        start=candidate[0].start,
                        end=candidate[-1].end,
                    )
                )
            if not options:
                raise ValueError(f"No feasible placement for session {session.session_id}")
            self.session_options[session.session_id] = options

    def _collect_contiguous_slots(
        self, ordered_slots: List[TimeSlot], start_index: int, duration_minutes: int
    ) -> List[TimeSlot]:
        total = 0
        collected: List[TimeSlot] = []
        previous_end = None
        for slot in ordered_slots[start_index:]:
            if collected and slot.day != collected[-1].day:
                break
            if previous_end is not None and slot.start != previous_end:
                break
            collected.append(slot)
            total += minutes_between(slot.start, slot.end)
            previous_end = slot.end
            if total == duration_minutes:
                return collected
            if total > duration_minutes:
                break
        return []

    # ------------------------------------------------------------------
    # Variable creation
    # ------------------------------------------------------------------
    def _create_assignment_variables(
        self,
        teachers: Dict[str, Teacher],
        rooms: Dict[str, Room],
        groups: Dict[str, Group],
        courses: Dict[str, Course],
    ) -> None:
        slot_ids = [slot.slot_id for slot in self.data.time_grid]
        slot_index = {slot_id: idx for idx, slot_id in enumerate(slot_ids)}
        for session in self.sessions:
            options = self.session_options[session.session_id]
            option_vars = {
                option.option_id: self.model.NewBoolVar(f"opt[{session.session_id},{option.option_id}]")
                for option in options
            }
            self.model.Add(sum(option_vars.values()) == 1).WithName(
                f"session_option_unique[{session.session_id}]"
            )
            self.variables.setdefault("session_option", {})[session.session_id] = option_vars

            slot_usage: Dict[str, cp_model.IntVar] = {}
            for slot_id in slot_ids:
                var = self.model.NewBoolVar(f"session_slot[{session.session_id},{slot_id}]")
                relevant_options = [
                    option_vars[option.option_id]
                    for option in options
                    if slot_id in option.slot_ids
                ]
                if relevant_options:
                    self.model.Add(var == sum(relevant_options)).WithName(
                        f"session_slot_link[{session.session_id},{slot_id}]"
                    )
                else:
                    self.model.Add(var == 0)
                slot_usage[slot_id] = var
            self.variables.setdefault("session_slot", {})[session.session_id] = slot_usage

            teacher_vars: Dict[str, cp_model.IntVar] = {}
            for teacher_id, teacher in teachers.items():
                allowed_types = teacher.can_teach.get(session.module_id, [])
                if session.type not in allowed_types:
                    continue
                teacher_vars[teacher_id] = self.model.NewBoolVar(
                    f"teacher_assign[{session.session_id},{teacher_id}]"
                )
            if not teacher_vars:
                raise ValueError(f"No teacher available for session {session.session_id}")
            self.model.Add(sum(teacher_vars.values()) == 1).WithName(
                f"session_teacher_unique[{session.session_id}]"
            )
            self.variables.setdefault("session_teacher", {})[session.session_id] = teacher_vars

            course = courses[session.course_id]
            total_group_size = sum(groups[group_id].size for group_id in session.groups)
            room_vars: Dict[str, cp_model.IntVar] = {}
            for room_id, room in rooms.items():
                if room.capacity < total_group_size:
                    continue
                if not course.required_equipment.issubset(room.equipment):
                    continue
                room_vars[room_id] = self.model.NewBoolVar(
                    f"room_assign[{session.session_id},{room_id}]"
                )
            if not room_vars:
                raise ValueError(f"No compatible room for session {session.session_id}")
            self.model.Add(sum(room_vars.values()) == 1).WithName(
                f"session_room_unique[{session.session_id}]"
            )
            self.variables.setdefault("session_room", {})[session.session_id] = room_vars

            start_var = self.model.NewIntVar(0, len(slot_ids) - 1, f"start_idx[{session.session_id}]")
            end_var = self.model.NewIntVar(0, len(slot_ids) - 1, f"end_idx[{session.session_id}]")
            self.variables.setdefault("session_start", {})[session.session_id] = start_var
            self.variables.setdefault("session_end", {})[session.session_id] = end_var
            self.model.Add(
                start_var
                == sum(slot_index[option.slot_ids[0]] * option_vars[option.option_id] for option in options)
            ).WithName(f"start_index[{session.session_id}]")
            self.model.Add(
                end_var
                == sum(slot_index[option.slot_ids[-1]] * option_vars[option.option_id] for option in options)
            ).WithName(f"end_index[{session.session_id}]")

    # ------------------------------------------------------------------
    # Hard constraints
    # ------------------------------------------------------------------
    def _add_teacher_constraints(self, teachers: Dict[str, Teacher]) -> None:
        slot_ids = [slot.slot_id for slot in self.data.time_grid]
        # Availability and incompatibility with forbidden slots
        for session in self.sessions:
            options = self.session_options[session.session_id]
            option_vars = self.variables["session_option"][session.session_id]
            for teacher_id, assign_var in self.variables["session_teacher"][session.session_id].items():
                teacher = teachers[teacher_id]
                incompatible_options = [
                    option
                    for option in options
                    if any(
                        slot_id not in teacher.availability
                        or slot_id in teacher.hard_unavailability
                        for slot_id in option.slot_ids
                    )
                ]
                for option in incompatible_options:
                    self.model.Add(assign_var + option_vars[option.option_id] <= 1).WithName(
                        f"teacher_availability[{session.session_id},{teacher_id},{option.option_id}]"
                    )

        # Teacher cannot teach two sessions simultaneously
        teacher_slot_usage: Dict[str, Dict[str, cp_model.IntVar]] = defaultdict(dict)
        for teacher_id in teachers:
            for slot_id in slot_ids:
                slot_var = self.model.NewBoolVar(
                    f"teacher_slot[{teacher_id},{slot_id}]"
                )
                usage_vars: List[cp_model.IntVar] = []
                for session in self.sessions:
                    session_slot = self.variables["session_slot"][session.session_id][slot_id]
                    teacher_vars = self.variables["session_teacher"][session.session_id]
                    if teacher_id not in teacher_vars:
                        continue
                    indicator = self.model.NewBoolVar(
                        f"teacher_usage[{teacher_id},{session.session_id},{slot_id}]"
                    )
                    self.model.Add(indicator <= session_slot)
                    self.model.Add(indicator <= teacher_vars[teacher_id])
                    self.model.Add(indicator >= session_slot + teacher_vars[teacher_id] - 1)
                    usage_vars.append(indicator)
                if usage_vars:
                    self.model.Add(sum(usage_vars) <= 1).WithName(
                        f"teacher_unique[{teacher_id},{slot_id}]"
                    )
                    self.model.Add(slot_var == sum(usage_vars)).WithName(
                        f"teacher_slot_link[{teacher_id},{slot_id}]"
                    )
                else:
                    self.model.Add(slot_var == 0)
                teacher_slot_usage[teacher_id][slot_id] = slot_var
        self.variables["teacher_slot_usage"] = teacher_slot_usage

    def _add_group_constraints(self, groups: Dict[str, Group]) -> None:
        slot_ids = [slot.slot_id for slot in self.data.time_grid]
        # Direct group conflicts
        group_slot_usage: Dict[str, Dict[str, cp_model.IntVar]] = defaultdict(dict)
        for group_id in groups:
            for slot_id in slot_ids:
                slot_var = self.model.NewBoolVar(
                    f"group_slot[{group_id},{slot_id}]"
                )
                usage_vars = [
                    self.variables["session_slot"][session.session_id][slot_id]
                    for session in self.sessions
                    if group_id in session.groups
                ]
                if usage_vars:
                    self.model.Add(sum(usage_vars) <= 1).WithName(
                        f"group_unique[{group_id},{slot_id}]"
                    )
                    self.model.Add(slot_var == sum(usage_vars)).WithName(
                        f"group_slot_link[{group_id},{slot_id}]"
                    )
                else:
                    self.model.Add(slot_var == 0)
                group_slot_usage[group_id][slot_id] = slot_var
        self.variables["group_slot_usage"] = group_slot_usage
        # Linked group incompatibilities
        for group in groups.values():
            for other_id in group.incompatible_with:
                for slot_id in slot_ids:
                    usage_vars = [
                        self.variables["session_slot"][session.session_id][slot_id]
                        for session in self.sessions
                        if group.group_id in session.groups or other_id in session.groups
                    ]
                    if usage_vars:
                        self.model.Add(sum(usage_vars) <= 1).WithName(
                            f"group_incompat[{group.group_id},{other_id},{slot_id}]"
                        )

    def _add_room_constraints(self, rooms: Dict[str, Room]) -> None:
        slot_ids = [slot.slot_id for slot in self.data.time_grid]
        for room_id in rooms:
            for slot_id in slot_ids:
                usage_vars: List[cp_model.IntVar] = []
                for session in self.sessions:
                    room_vars = self.variables["session_room"][session.session_id]
                    if room_id not in room_vars:
                        continue
                    session_slot = self.variables["session_slot"][session.session_id][slot_id]
                    indicator = self.model.NewBoolVar(
                        f"room_usage[{room_id},{session.session_id},{slot_id}]"
                    )
                    self.model.Add(indicator <= room_vars[room_id])
                    self.model.Add(indicator <= session_slot)
                    self.model.Add(indicator >= room_vars[room_id] + session_slot - 1)
                    usage_vars.append(indicator)
                if usage_vars:
                    self.model.Add(sum(usage_vars) <= 1).WithName(
                        f"room_unique[{room_id},{slot_id}]"
                    )

    def _add_precedence_constraints(self, courses: Dict[str, Course]) -> None:
        start_vars = self.variables["session_start"]
        end_vars = self.variables["session_end"]
        for session in self.sessions:
            course = courses[session.course_id]
            for prereq_id in course.precedence:
                for prereq_session in self.sessions:
                    if prereq_session.course_id != prereq_id:
                        continue
                    self.model.Add(
                        start_vars[session.session_id]
                        >= end_vars[prereq_session.session_id] + 1
                    ).WithName(
                        f"precedence[{prereq_session.session_id}->{session.session_id}]"
                    )

    def _add_calendar_constraints(
        self,
        teachers: Dict[str, Teacher],
        groups: Dict[str, Group],
        rules: GlobalRules,
    ) -> None:
        if rules.lunch_start and rules.lunch_end:
            self._enforce_lunch_break_teachers(teachers, rules)
            self._enforce_lunch_break_groups(groups, rules)
        if rules.daily_amplitude_minutes is not None:
            self._enforce_daily_amplitude_teachers(teachers, rules.daily_amplitude_minutes)
            self._enforce_daily_amplitude_groups(groups, rules.daily_amplitude_minutes)

    def _enforce_lunch_break_teachers(self, teachers: Dict[str, Teacher], rules: GlobalRules) -> None:
        lunch_slots = [
            slot
            for slot in self.data.time_grid
            if not (slot.end <= rules.lunch_start or slot.start >= rules.lunch_end)
        ]
        if not lunch_slots:
            return
        slots_by_day: Dict[date, List[str]] = defaultdict(list)
        for slot in lunch_slots:
            slots_by_day[slot.day].append(slot.slot_id)
        teacher_slot_usage: Dict[str, Dict[str, cp_model.IntVar]] = self.variables.get(
            "teacher_slot_usage", {}
        )
        for teacher_id, slots_map in teacher_slot_usage.items():
            for day, day_slots in slots_by_day.items():
                daily_slots = [slot_id for slot_id in day_slots if slot_id in slots_map]
                if not daily_slots:
                    continue
                self.model.Add(
                    sum(slots_map[slot_id] for slot_id in daily_slots)
                    <= max(len(daily_slots) - 1, 0)
                ).WithName(f"teacher_lunch_break[{teacher_id},{day}]")

    def _enforce_lunch_break_groups(self, groups: Dict[str, Group], rules: GlobalRules) -> None:
        lunch_slots = [
            slot
            for slot in self.data.time_grid
            if not (slot.end <= rules.lunch_start or slot.start >= rules.lunch_end)
        ]
        if not lunch_slots:
            return
        slots_by_day: Dict[date, List[str]] = defaultdict(list)
        for slot in lunch_slots:
            slots_by_day[slot.day].append(slot.slot_id)
        group_slot_usage: Dict[str, Dict[str, cp_model.IntVar]] = self.variables.get(
            "group_slot_usage", {}
        )
        for group_id, slots_map in group_slot_usage.items():
            for day, day_slots in slots_by_day.items():
                daily_slots = [slot_id for slot_id in day_slots if slot_id in slots_map]
                if not daily_slots:
                    continue
                self.model.Add(
                    sum(slots_map[slot_id] for slot_id in daily_slots)
                    <= max(len(daily_slots) - 1, 0)
                ).WithName(f"group_lunch_break[{group_id},{day}]")

    def _enforce_daily_amplitude_teachers(self, teachers: Dict[str, Teacher], limit_minutes: int) -> None:
        slots_by_day: Dict[date, List[str]] = defaultdict(list)
        ordered_slot_ids = [slot.slot_id for slot in self.data.time_grid]
        slot_positions = {slot_id: idx for idx, slot_id in enumerate(ordered_slot_ids)}
        for slot in self.data.time_grid:
            slots_by_day[slot.day].append(slot.slot_id)
        max_distance = limit_minutes // 30
        teacher_slot_usage: Dict[str, Dict[str, cp_model.IntVar]] = self.variables.get(
            "teacher_slot_usage", {}
        )
        for teacher_id, slots_map in teacher_slot_usage.items():
            for day, day_slots in slots_by_day.items():
                for earlier in day_slots:
                    for later in day_slots:
                        if slot_positions[later] - slot_positions[earlier] > max_distance:
                            if earlier in slots_map and later in slots_map:
                                self.model.Add(
                                    slots_map[earlier] + slots_map[later] <= 1
                                ).WithName(
                                    f"teacher_amplitude[{teacher_id},{day},{earlier}->{later}]"
                                )

    def _enforce_daily_amplitude_groups(self, groups: Dict[str, Group], limit_minutes: int) -> None:
        slots_by_day: Dict[date, List[str]] = defaultdict(list)
        ordered_slot_ids = [slot.slot_id for slot in self.data.time_grid]
        slot_positions = {slot_id: idx for idx, slot_id in enumerate(ordered_slot_ids)}
        for slot in self.data.time_grid:
            slots_by_day[slot.day].append(slot.slot_id)
        max_distance = limit_minutes // 30
        group_slot_usage: Dict[str, Dict[str, cp_model.IntVar]] = self.variables.get(
            "group_slot_usage", {}
        )
        for group_id, slots_map in group_slot_usage.items():
            for day, day_slots in slots_by_day.items():
                for earlier in day_slots:
                    for later in day_slots:
                        if slot_positions[later] - slot_positions[earlier] > max_distance:
                            if earlier in slots_map and later in slots_map:
                                self.model.Add(
                                    slots_map[earlier] + slots_map[later] <= 1
                                ).WithName(
                                    f"group_amplitude[{group_id},{day},{earlier}->{later}]"
                                )


def build_model(data: SchedulerInput, config: SchedulerConfig) -> SchedulerModel:
    """Build the CP-SAT model for the given validated input dataset."""

    builder = ModelBuilder(data, config)
    return builder.build()
