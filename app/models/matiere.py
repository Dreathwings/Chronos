from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import db


class Matiere(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(unique=True, nullable=False)
    description: Mapped[str | None]
    sessions_a_planifier: Mapped[int] = mapped_column(default=1)
    duree_par_session: Mapped[int] = mapped_column(default=2, doc="Durée en heures")
    priorite: Mapped[int] = mapped_column(default=1)
    besoins_materiel: Mapped[str | None]
    besoins_logiciel: Mapped[str | None]
    couleur: Mapped[str | None] = mapped_column(doc="Couleur pour FullCalendar")

    sessions: Mapped[list["Session"]] = relationship(back_populates="matiere")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Matiere {self.nom}>"
