import click
from flask import Flask, current_app
from flask.cli import with_appcontext
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload
import os
from config import Config, _normalise_prefix



db = SQLAlchemy()
migrate = Migrate()


def _realign_tp_session_teachers() -> int:
    """Realign TP sessions with the teacher assigned to their subgroup."""

    from .models import Course, Session

    updated = 0
    sessions = (
        Session.query.options(
            selectinload(Session.course).selectinload(Course.class_links),
            selectinload(Session.class_group),
            selectinload(Session.teacher),
        )
        .filter(Session.subgroup_label.isnot(None))
        .all()
    )
    for session in sessions:
        course = session.course
        class_group = session.class_group
        if course is None or class_group is None:
            continue
        link = next(
            (
                link
                for link in course.class_links
                if link.class_group_id == class_group.id
            ),
            None,
        )
        if link is None or link.group_count != 2:
            continue
        assigned = link.teacher_for_label(session.subgroup_label)
        if assigned is None or session.teacher_id == assigned.id:
            continue
        session.teacher = assigned
        updated += 1
    if updated:
        db.session.commit()
    return updated


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_class)

    url_prefix = _normalise_prefix(app.config.get("URL_PREFIX", ""))
    app.config["URL_PREFIX"] = url_prefix

    static_folder = os.path.join(app.root_path, "static")
    app.static_folder = static_folder

    static_url_path = f"{url_prefix}/static" if url_prefix else "/static"
    app.static_url_path = static_url_path
    app.add_url_rule(
        f"{static_url_path}/<path:filename>",
        endpoint="static",
        view_func=app.send_static_file,
    )

    if url_prefix:
        app.add_url_rule(
            "/static/<path:filename>",
            endpoint="static_without_prefix",
            view_func=app.send_static_file,
        )
    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401  # Ensure models registered for migrations

    with app.app_context():
        db.create_all()
        _ensure_session_class_group_column()
        _ensure_session_subgroup_column()
        _ensure_session_subgroup_uniqueness_constraint()
        _ensure_course_class_group_count_column()
        _ensure_course_class_subgroup_name_columns()
        _ensure_course_class_teacher_columns()
        _ensure_course_type_column()
        _ensure_course_semester_column()
        _ensure_course_course_name_column()
        _ensure_session_attendance_backfill()
        updated_sessions = _realign_tp_session_teachers()
        if updated_sessions:
            app.logger.info(
                "Realigned %s TP session(s) with their subgroup teacher.",
                updated_sessions,
            )

    from .routes import bp as main_bp

    app.register_blueprint(main_bp, url_prefix=url_prefix or None)

    @app.cli.command("seed")
    @with_appcontext
    def seed() -> None:
        """Seed initial data for development."""
        from .seed import seed_data

        seed_data()
        print("Database seeded with sample data.")

    @app.cli.command("clean-session-teachers")
    @with_appcontext
    def clean_session_teachers() -> None:
        """Realign TP sessions with their subgroup teachers."""
        updated = _realign_tp_session_teachers()
        click.echo(f"{updated} séance(s) corrigée(s).")

    return app


def _ensure_session_class_group_column() -> None:
    """Add the class_group_id column to existing session tables if missing."""
    engine = db.engine
    inspector = inspect(engine)
    if "session" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("session")}
    if "class_group_id" in existing_columns:
        return

    from .models import ClassGroup  # Imported lazily to avoid circular imports

    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE session ADD COLUMN class_group_id INTEGER"))
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard for legacy DBs
        current_app.logger.warning("Unable to add class_group_id column: %s", exc)
        return

    default_class = ClassGroup.query.filter_by(name="Classe non assignée").first()
    if default_class is None:
        default_class = ClassGroup(name="Classe non assignée", notes="Créée automatiquement pour les séances existantes.")
        db.session.add(default_class)
        db.session.commit()

    db.session.execute(
        text("UPDATE session SET class_group_id = :class_id WHERE class_group_id IS NULL"),
        {"class_id": default_class.id},
    )
    db.session.commit()

    if engine.dialect.name not in {"sqlite"}:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE session MODIFY class_group_id INTEGER NOT NULL"
                    )
                )
                connection.execute(
                    text(
                        "ALTER TABLE session ADD CONSTRAINT session_class_group_fk "
                        "FOREIGN KEY (class_group_id) REFERENCES class_group (id)"
                    )
                )
        except SQLAlchemyError:
            current_app.logger.warning(
                "Unable to tighten constraints on session.class_group_id; continuing with nullable column."
            )


def _ensure_course_class_group_count_column() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "course_class" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("course_class")}
    if "group_count" in existing_columns:
        return

    try:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE course_class ADD COLUMN group_count INTEGER DEFAULT 1")
            )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning("Unable to add group_count column to course_class: %s", exc)
        return

    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE course_class SET group_count = 1 WHERE group_count IS NULL")
            )
    except SQLAlchemyError as exc:  # pragma: no cover
        current_app.logger.warning("Unable to backfill group_count column: %s", exc)
        return

    if engine.dialect.name not in {"sqlite"}:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE course_class MODIFY group_count INTEGER NOT NULL")
                )
        except SQLAlchemyError:
            current_app.logger.warning(
                "Unable to tighten constraints on course_class.group_count; continuing with nullable column."
            )

def _ensure_session_subgroup_column() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "session" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("session")}
    if "subgroup_label" in existing_columns:
        return

    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE session ADD COLUMN subgroup_label VARCHAR(1)"))
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning("Unable to add subgroup_label column to session: %s", exc)


def _ensure_session_subgroup_uniqueness_constraint() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "session" not in inspector.get_table_names():
        return

    desired_columns = {"class_group_id", "subgroup_label", "start_time"}
    unique_constraints = inspector.get_unique_constraints("session")
    constraint = next((uc for uc in unique_constraints if uc.get("name") == "uq_class_start_time"), None)
    if constraint and set(constraint.get("column_names", [])) == desired_columns:
        return

    dialect = engine.dialect.name
    statements: list[str] = []
    if dialect == "mysql":
        if constraint:
            statements.append("ALTER TABLE session DROP INDEX uq_class_start_time")
        statements.append("ALTER TABLE session ADD CONSTRAINT uq_class_start_time UNIQUE (class_group_id, subgroup_label, start_time)")
    elif dialect == "postgresql":
        statements.append("ALTER TABLE session DROP CONSTRAINT IF EXISTS uq_class_start_time")
        statements.append("ALTER TABLE session ADD CONSTRAINT uq_class_start_time UNIQUE (class_group_id, subgroup_label, start_time)")
    elif dialect == "sqlite":
        statements.append("DROP INDEX IF EXISTS uq_class_start_time")
        statements.append("CREATE UNIQUE INDEX IF NOT EXISTS uq_class_start_time ON session (class_group_id, subgroup_label, start_time)")
    else:
        statements.append("ALTER TABLE session DROP CONSTRAINT uq_class_start_time")
        statements.append("ALTER TABLE session ADD CONSTRAINT uq_class_start_time UNIQUE (class_group_id, subgroup_label, start_time)")

    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning("Unable to realign session subgroup uniqueness constraint: %s", exc)


def _ensure_course_class_teacher_columns() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "course_class" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("course_class")}
    statements: list[str] = []
    if "teacher_a_id" not in existing_columns:
        statements.append("ALTER TABLE course_class ADD COLUMN teacher_a_id INTEGER")
    if "teacher_b_id" not in existing_columns:
        statements.append("ALTER TABLE course_class ADD COLUMN teacher_b_id INTEGER")

    if not statements:
        return

    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    except SQLAlchemyError as exc:  # pragma: no cover
        current_app.logger.warning("Unable to add teacher columns to course_class: %s", exc)


def _ensure_course_class_subgroup_name_columns() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "course_class" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("course_class")}
    statements: list[str] = []
    if "subgroup_a_course_name_id" not in existing_columns:
        statements.append("ALTER TABLE course_class ADD COLUMN subgroup_a_course_name_id INTEGER")
    if "subgroup_b_course_name_id" not in existing_columns:
        statements.append("ALTER TABLE course_class ADD COLUMN subgroup_b_course_name_id INTEGER")

    if not statements:
        return

    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    except SQLAlchemyError as exc:  # pragma: no cover
        current_app.logger.warning(
            "Unable to add subgroup name columns to course_class: %s", exc
        )


def _ensure_course_type_column() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "course" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("course")}
    if "course_type" in existing_columns:
        return

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE course ADD COLUMN course_type VARCHAR(3) NOT NULL DEFAULT 'CM'"
                )
            )
            connection.execute(
                text("UPDATE course SET course_type = 'CM' WHERE course_type IS NULL")
            )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning("Unable to add course_type column to course: %s", exc)
        return

    if engine.dialect.name not in {"sqlite"}:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE course MODIFY course_type VARCHAR(3) NOT NULL DEFAULT 'CM'"
                    )
                )
        except SQLAlchemyError:
            current_app.logger.warning(
                "Unable to tighten constraints on course.course_type; continuing with relaxed column."
            )


def _ensure_course_semester_column() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "course" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("course")}
    if "semester" in existing_columns:
        return

    try:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE course ADD COLUMN semester VARCHAR(2) DEFAULT 'S1'")
            )
            connection.execute(
                text("UPDATE course SET semester = 'S1' WHERE semester IS NULL")
            )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard for legacy DBs
        current_app.logger.warning("Unable to add semester column to course: %s", exc)
        return

    if engine.dialect.name not in {"sqlite"}:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE course MODIFY semester VARCHAR(2) NOT NULL DEFAULT 'S1'"
                    )
                )
        except SQLAlchemyError:
            current_app.logger.warning(
                "Unable to tighten constraints on course.semester; continuing with relaxed column."
            )


def _ensure_course_course_name_column() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "course" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("course")}
    if "course_name_id" in existing_columns:
        return

    try:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE course ADD COLUMN course_name_id INTEGER")
            )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard for legacy DBs
        current_app.logger.warning("Unable to add course_name_id column to course: %s", exc)
        return

    if engine.dialect.name not in {"sqlite"}:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE course ADD CONSTRAINT course_course_name_fk "
                        "FOREIGN KEY (course_name_id) REFERENCES course_name (id)"
                    )
                )
        except SQLAlchemyError:
            current_app.logger.warning(
                "Unable to add foreign key constraint to course.course_name_id; continuing without constraint."
            )


def _ensure_session_attendance_backfill() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "session_attendance" not in inspector.get_table_names():
        return

    try:
        with engine.begin() as connection:
            count = connection.execute(
                text("SELECT COUNT(*) FROM session_attendance")
            ).scalar()
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning(
            "Unable to inspect session_attendance table: %s", exc
        )
        return

    if count and int(count) > 0:
        return

    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO session_attendance (session_id, class_group_id) "
                    "SELECT id, class_group_id FROM session WHERE class_group_id IS NOT NULL"
                )
            )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning(
            "Unable to backfill session_attendance table: %s", exc
        )

