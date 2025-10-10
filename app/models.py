from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )


class Enseignant(TimestampMixin, Base):
    __tablename__ = "enseignants"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    disponibilites: Mapped[str | None] = mapped_column(Text())

    cours: Mapped[list[SessionCours]] = relationship(back_populates="enseignant", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Enseignant(id={self.id!r}, nom={self.nom!r})"


class Salle(TimestampMixin, Base):
    __tablename__ = "salles"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    capacite: Mapped[int | None] = mapped_column(Integer())
    equipements: Mapped[str | None] = mapped_column(Text())

    cours: Mapped[list[SessionCours]] = relationship(back_populates="salle", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"Salle(id={self.id!r}, nom={self.nom!r})"


class Matiere(TimestampMixin, Base):
    __tablename__ = "matieres"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text())
    duree: Mapped[int] = mapped_column(Integer(), default=60)  # minutes
    fenetre_debut: Mapped[date | None] = mapped_column(Date())
    fenetre_fin: Mapped[date | None] = mapped_column(Date())
    besoins: Mapped[str | None] = mapped_column(Text())
    priorite: Mapped[int] = mapped_column(Integer(), default=1)

    sessions: Mapped[list[SessionCours]] = relationship(back_populates="matiere", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"Matiere(id={self.id!r}, nom={self.nom!r})"


class SessionCours(TimestampMixin, Base):
    __tablename__ = "sessions_cours"

    id: Mapped[int] = mapped_column(primary_key=True)
    matiere_id: Mapped[int] = mapped_column(ForeignKey("matieres.id", ondelete="CASCADE"), nullable=False)
    enseignant_id: Mapped[int] = mapped_column(ForeignKey("enseignants.id", ondelete="SET NULL"))
    salle_id: Mapped[int] = mapped_column(ForeignKey("salles.id", ondelete="SET NULL"))
    date: Mapped[date] = mapped_column(Date(), nullable=False)
    debut: Mapped[time] = mapped_column(Time(), nullable=False)
    fin: Mapped[time] = mapped_column(Time(), nullable=False)

    matiere: Mapped[Matiere] = relationship(back_populates="sessions")
    enseignant: Mapped[Enseignant] = relationship(back_populates="cours")
    salle: Mapped[Salle] = relationship(back_populates="cours")

    def __repr__(self) -> str:  # pragma: no cover
        return f"SessionCours(id={self.id!r}, matiere={self.matiere_id!r})"
