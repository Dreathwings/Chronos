from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import db


class Salle(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(unique=True, nullable=False)
    capacite: Mapped[int] = mapped_column(default=30)
    nombre_pc: Mapped[int] = mapped_column(default=0)
    equipements: Mapped[str | None]

    sessions: Mapped[list["Session"]] = relationship(back_populates="salle")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Salle {self.nom}>"
