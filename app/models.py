from __future__ import annotations

from datetime import date, time

from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import db


class Enseignant(db.Model):
    __tablename__ = "enseignants"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(nullable=False)
    email: Mapped[str] = mapped_column(nullable=False, unique=True)
    disponibilites: Mapped[str] = mapped_column(
        nullable=False,
        default="",
        doc="Disponibilités formatées en texte libre ou JSON.",
    )

    matieres: Mapped[list["Matiere"]] = relationship(back_populates="enseignant")
    creneaux: Mapped[list["Creneau"]] = relationship(back_populates="enseignant")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Enseignant {self.nom}>"


class Salle(db.Model):
    __tablename__ = "salles"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(nullable=False, unique=True)
    capacite: Mapped[int] = mapped_column(nullable=False)
    equipements: Mapped[str] = mapped_column(nullable=False, default="")
    disponibilites: Mapped[str] = mapped_column(nullable=False, default="")

    creneaux: Mapped[list["Creneau"]] = relationship(back_populates="salle")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Salle {self.nom}>"


class Matiere(db.Model):
    __tablename__ = "matieres"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(nullable=False)
    duree: Mapped[int] = mapped_column(nullable=False, default=1)
    capacite_requise: Mapped[int] = mapped_column(nullable=False, default=1)
    fenetre_debut: Mapped[date | None] = mapped_column(nullable=True)
    fenetre_fin: Mapped[date | None] = mapped_column(nullable=True)
    besoins: Mapped[str] = mapped_column(nullable=False, default="")
    logiciels: Mapped[str] = mapped_column(nullable=False, default="")
    priorite: Mapped[int] = mapped_column(nullable=False, default=1)

    enseignant_id: Mapped[int | None] = mapped_column(ForeignKey("enseignants.id"))
    enseignant: Mapped[Enseignant | None] = relationship(back_populates="matieres")

    creneaux: Mapped[list["Creneau"]] = relationship(back_populates="matiere")

    __table_args__ = (
        CheckConstraint("duree > 0", name="ck_matiere_duree_positive"),
        CheckConstraint("priorite >= 0", name="ck_matiere_priorite_positive"),
        CheckConstraint(
            "capacite_requise > 0", name="ck_matiere_capacite_positive"
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Matiere {self.nom}>"


class Creneau(db.Model):
    __tablename__ = "creneaux"

    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(nullable=False)
    debut: Mapped[time] = mapped_column(nullable=False)
    fin: Mapped[time] = mapped_column(nullable=False)

    matiere_id: Mapped[int] = mapped_column(ForeignKey("matieres.id"), nullable=False)
    salle_id: Mapped[int] = mapped_column(ForeignKey("salles.id"), nullable=False)
    enseignant_id: Mapped[int] = mapped_column(ForeignKey("enseignants.id"), nullable=False)

    matiere: Mapped[Matiere] = relationship(back_populates="creneaux")
    salle: Mapped[Salle] = relationship(back_populates="creneaux")
    enseignant: Mapped[Enseignant] = relationship(back_populates="creneaux")

    __table_args__ = (
        CheckConstraint("debut < fin", name="ck_creneau_duree_positive"),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Creneau {self.matiere.nom} {self.date} {self.debut}-{self.fin}>"
