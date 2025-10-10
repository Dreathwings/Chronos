"""Initial database schema"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=120), nullable=False, unique=True),
        sa.Column("phone_number", sa.String(length=30)),
        sa.Column("availability", sa.Text()),
        sa.Column("max_weekly_hours", sa.Integer(), nullable=False, server_default="20"),
    )

    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False, unique=True),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("location", sa.String(length=120)),
        sa.Column("equipments", sa.Text()),
        sa.Column("has_computers", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=30), nullable=False, unique=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("duration_hours", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_date", sa.Date()),
        sa.Column("end_date", sa.Date()),
        sa.Column("group_size", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("required_equipments", sa.Text()),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id", ondelete="SET NULL")),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id", ondelete="SET NULL")),
        sa.CheckConstraint("duration_hours > 0", name="ck_course_duration_positive"),
        sa.CheckConstraint("group_size > 0", name="ck_course_group_size_positive"),
    )

    op.create_table(
        "course_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("room_id", sa.Integer(), sa.ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.CheckConstraint("day_of_week >= 0 AND day_of_week <= 6", name="ck_session_day"),
        sa.CheckConstraint("start_time < end_time", name="ck_session_time_order"),
    )


def downgrade() -> None:
    op.drop_table("course_sessions")
    op.drop_table("courses")
    op.drop_table("rooms")
    op.drop_table("teachers")
