from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from .. import db
from ..models import Enseignant, Matiere, Salle, Session


@dataclass
class StatItem:
    label: str
    value: Any
    icon: str


class QuickScheduler:
    """Minimal helper offering aggregated statistics.

    In a full implementation this class would orchestrate OR-Tools to optimise
    sessions placement. Here we focus on computing dashboard indicators that
    guide manual planning while keeping the structure extensible.
    """

    @classmethod
    def compute_stats(cls) -> list[StatItem]:
        total_sessions = db.session.scalar(select(func.count(Session.id))) or 0
        total_hours = sum(session.duree_heures for session in db.session.scalars(select(Session)).all())
        enseignants_count = db.session.scalar(select(func.count(Enseignant.id))) or 0
        salles_count = db.session.scalar(select(func.count(Salle.id))) or 0
        matieres_count = db.session.scalar(select(func.count(Matiere.id))) or 0

        return [
            StatItem("Séances planifiées", total_sessions, "calendar"),
            StatItem("Heures totales", round(total_hours, 2), "clock"),
            StatItem("Enseignants", enseignants_count, "user"),
            StatItem("Salles", salles_count, "map-marker"),
            StatItem("Cours", matieres_count, "book"),
        ]
