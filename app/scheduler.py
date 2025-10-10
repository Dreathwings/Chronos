from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Iterable

from ortools.sat.python import cp_model

from .database import db
from .models import Creneau, Matiere, Salle


SLOTS = [
    (time(hour=8), time(hour=9)),
    (time(hour=9), time(hour=10)),
    (time(hour=10, minute=15), time(hour=11, minute=15)),
    (time(hour=11, minute=15), time(hour=12, minute=15)),
    (time(hour=13, minute=30), time(hour=14, minute=30)),
    (time(hour=14, minute=30), time(hour=15, minute=30)),
    (time(hour=15, minute=45), time(hour=16, minute=45)),
    (time(hour=16, minute=45), time(hour=17, minute=45)),
]


@dataclass
class ScheduleResult:
    matiere: Matiere
    salle: Salle
    jour: date
    debut: time
    fin: time


def generate_candidate_days(matiere: Matiere, horizon_days: int = 14) -> list[date]:
    today = date.today()
    start = matiere.fenetre_debut or today
    end = matiere.fenetre_fin or (start + timedelta(days=horizon_days))
    if start > end:
        start, end = end, start
    days: list[date] = []
    current = start
    while current <= end and len(days) < horizon_days:
        if current.weekday() < 5:  # Lundi-vendredi
            days.append(current)
        current += timedelta(days=1)
    if not days:
        days.append(today)
    return days


def build_schedule(
    matieres: Iterable[Matiere], salles: Iterable[Salle]
) -> list[ScheduleResult]:
    matieres = [m for m in matieres if m.enseignant is not None]
    salles = list(salles)
    if not matieres or not salles:
        return []

    model = cp_model.CpModel()

    candidate_days = {matiere.id: generate_candidate_days(matiere) for matiere in matieres}
    matiere_by_id = {matiere.id: matiere for matiere in matieres}

    x: dict[tuple[int, int, int, int], cp_model.IntVar] = {}
    for matiere in matieres:
        duration = max(1, matiere.duree)
        for salle in salles:
            if salle.capacite < matiere.capacite_requise:
                continue
            for day_index, _ in enumerate(candidate_days[matiere.id]):
                for slot_index in range(len(SLOTS) - duration + 1):
                    var = model.NewBoolVar(
                        f"assign_m{matiere.id}_r{salle.id}_d{day_index}_s{slot_index}"
                    )
                    x[(matiere.id, salle.id, day_index, slot_index)] = var

    for matiere in matieres:
        vars_for_matiere = [var for key, var in x.items() if key[0] == matiere.id]
        if vars_for_matiere:
            model.Add(sum(vars_for_matiere) == 1)

    max_day_count = max((len(days) for days in candidate_days.values()), default=0)

    for salle in salles:
        for day_index in range(max_day_count):
            for slot_index in range(len(SLOTS)):
                overlapping = []
                for (matiere_id, salle_id, start_day, start_slot), var in x.items():
                    if salle_id != salle.id or start_day != day_index:
                        continue
                    matiere = matiere_by_id[matiere_id]
                    duration = max(1, matiere.duree)
                    if start_slot <= slot_index < start_slot + duration:
                        overlapping.append(var)
                if overlapping:
                    model.Add(sum(overlapping) <= 1)

    enseignant_ids = {matiere.enseignant_id for matiere in matieres if matiere.enseignant_id}
    for enseignant_id in enseignant_ids:
        for day_index in range(max_day_count):
            for slot_index in range(len(SLOTS)):
                overlapping = []
                for (matiere_id, salle_id, start_day, start_slot), var in x.items():
                    if start_day != day_index:
                        continue
                    matiere = matiere_by_id[matiere_id]
                    if matiere.enseignant_id != enseignant_id:
                        continue
                    duration = max(1, matiere.duree)
                    if start_slot <= slot_index < start_slot + duration:
                        overlapping.append(var)
                if overlapping:
                    model.Add(sum(overlapping) <= 1)

    model.Maximize(
        sum(
            var * matiere_by_id[matiere_id].priorite
            for (matiere_id, _salle_id, _day_index, _slot_index), var in x.items()
        )
    )

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5
    result = solver.Solve(model)
    if result not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return []

    scheduled: list[ScheduleResult] = []
    for (matiere_id, salle_id, day_index, slot_index), var in x.items():
        if solver.Value(var):
            matiere = matiere_by_id[matiere_id]
            salle = next(s for s in salles if s.id == salle_id)
            day = candidate_days[matiere.id][day_index]
            start_time = SLOTS[slot_index][0]
            end_time = SLOTS[min(slot_index + matiere.duree - 1, len(SLOTS) - 1)][1]
            scheduled.append(
                ScheduleResult(
                    matiere=matiere,
                    salle=salle,
                    jour=day,
                    debut=start_time,
                    fin=end_time,
                )
            )
    scheduled.sort(key=lambda item: (item.jour, item.debut, item.matiere.nom))
    return scheduled


def persist_schedule(results: Iterable[ScheduleResult]) -> list[Creneau]:
    created: list[Creneau] = []
    for result in results:
        creneau = Creneau(
            date=result.jour,
            debut=result.debut,
            fin=result.fin,
            matiere_id=result.matiere.id,
            salle_id=result.salle.id,
            enseignant_id=result.matiere.enseignant_id,
        )
        db.session.add(creneau)
        created.append(creneau)
    if created:
        db.session.commit()
    return created
