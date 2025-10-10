"""Initial schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20240510_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enseignants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nom", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True, unique=True),
        sa.Column("disponibilites", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "salles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nom", sa.String(length=120), nullable=False, unique=True),
        sa.Column("capacite", sa.Integer(), nullable=True),
        sa.Column("equipements", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "matieres",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nom", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duree", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("fenetre_debut", sa.Date(), nullable=True),
        sa.Column("fenetre_fin", sa.Date(), nullable=True),
        sa.Column("besoins", sa.Text(), nullable=True),
        sa.Column("priorite", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "sessions_cours",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("matiere_id", sa.Integer(), sa.ForeignKey("matieres.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enseignant_id", sa.Integer(), sa.ForeignKey("enseignants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("salle_id", sa.Integer(), sa.ForeignKey("salles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("debut", sa.Time(), nullable=False),
        sa.Column("fin", sa.Time(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("sessions_cours")
    op.drop_table("matieres")
    op.drop_table("salles")
    op.drop_table("enseignants")
