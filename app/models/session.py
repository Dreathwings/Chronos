from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import db
from .associations import session_enseignant


class Session(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    matiere_id: Mapped[int] = mapped_column(db.ForeignKey("matiere.id"), nullable=False)
    salle_id: Mapped[int | None] = mapped_column(db.ForeignKey("salle.id"))
    debut: Mapped[datetime] = mapped_column(nullable=False)
    fin: Mapped[datetime] = mapped_column(nullable=False)

    matiere: Mapped["Matiere"] = relationship(back_populates="sessions")
    salle: Mapped["Salle" | None] = relationship(back_populates="sessions")
    enseignants: Mapped[list["Enseignant"]] = relationship(
        secondary=session_enseignant,
        back_populates="sessions",
    )

    @property
    def duree_heures(self) -> float:
        delta = self.fin - self.debut
        return delta.total_seconds() / 3600

    def as_fullcalendar_event(self) -> dict[str, object]:
        enseignants = ", ".join(e.nom for e in self.enseignants) or "Enseignant à assigner"
        salle = self.salle.nom if self.salle else "Salle à confirmer"
        return {
            "id": self.id,
            "title": f"{self.matiere.nom} — {enseignants} ({salle})",
            "start": self.debut.isoformat(),
            "end": self.fin.isoformat(),
            "backgroundColor": self.matiere.couleur or "#2563eb",
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Session {self.matiere.nom} {self.debut:%Y-%m-%d %H:%M}>"
