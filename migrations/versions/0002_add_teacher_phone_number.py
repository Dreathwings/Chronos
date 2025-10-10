"""Add phone_number column to teachers"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_add_teacher_phone_number"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("teachers", sa.Column("phone_number", sa.String(length=30)))


def downgrade() -> None:
    op.drop_column("teachers", "phone_number")
