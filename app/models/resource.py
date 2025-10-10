from __future__ import annotations

from sqlalchemy.orm import Mapped, mapped_column

from .. import db


class Logiciel(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(unique=True, nullable=False)
    version: Mapped[str | None]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Logiciel {self.nom}>"


class Materiel(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(unique=True, nullable=False)
    description: Mapped[str | None]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Materiel {self.nom}>"
