from __future__ import annotations

from datetime import time

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import db
from .associations import session_enseignant


class Enseignant(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str | None] = mapped_column(unique=True)
    max_heures_semaine: Mapped[int] = mapped_column(default=20)
    disponibilites: Mapped[str | None] = mapped_column(
        doc="Description textuelle des disponibilités par créneau"
    )
    indisponibilites: Mapped[str | None] = mapped_column(
        doc="Liste des indisponibilités exceptionnelles"
    )

    sessions: Mapped[list["Session"]] = relationship(
        secondary=session_enseignant,
        back_populates="enseignants",
    )

    def heures_planifiees(self) -> float:
        return sum(session.duree_heures for session in self.sessions)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Enseignant {self.nom}>"
