import click
from collections import defaultdict
from typing import Optional
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
        _ensure_course_allowed_week_sessions_column()
        _ensure_course_color_column()
        _ensure_student_profile_columns()
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


def _quote_mysql_identifier(identifier: str) -> str:
    """Return a MySQL-safe quoted identifier."""

    escaped = identifier.replace("`", "``")
    return f"`{escaped}`"


def _ensure_session_subgroup_uniqueness_constraint() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "session" not in inspector.get_table_names():
        return

    desired_columns = {"class_group_id", "subgroup_label", "start_time"}
    legacy_columns = {"class_group_id", "start_time"}

    unique_structures: list[tuple[str, Optional[str], set[str]]] = []
    seen_structures: set[tuple[str, Optional[str], tuple[str, ...]]] = set()

    def _register_structure(kind: str, name: Optional[str], columns: list[str]) -> None:
        column_names = [col for col in columns if col]
        if not column_names:
            return
        key = (kind, name, tuple(column_names))
        if key in seen_structures:
            return
        seen_structures.add(key)
        unique_structures.append((kind, name, set(column_names)))

    for constraint in inspector.get_unique_constraints("session"):
        column_names = constraint.get("column_names") or []
        _register_structure("constraint", constraint.get("name"), column_names)

    for index in inspector.get_indexes("session"):
        if not index.get("unique"):
            continue
        column_names = index.get("column_names") or []
        _register_structure("index", index.get("name"), column_names)

    has_desired = any(columns == desired_columns for _, _, columns in unique_structures)
    legacy_targets = [
        (kind, name)
        for kind, name, columns in unique_structures
        if columns == legacy_columns
    ]

    dialect = engine.dialect.name

    if dialect == "mysql":
        with engine.connect() as connection:
            stats_rows = connection.execute(
                text(
                    """
                    SELECT INDEX_NAME, COLUMN_NAME, SEQ_IN_INDEX
                    FROM INFORMATION_SCHEMA.STATISTICS
                    WHERE TABLE_SCHEMA = DATABASE()
                      AND TABLE_NAME = 'session'
                      AND NON_UNIQUE = 0
                    ORDER BY INDEX_NAME, SEQ_IN_INDEX
                    """
                )
            ).mappings().all()

        ordered_indexes: dict[str, list[str]] = defaultdict(list)
        for row in stats_rows:
            index_name = row.get("INDEX_NAME")
            if not index_name or index_name.upper() == "PRIMARY":
                continue
            column_name = row.get("COLUMN_NAME")
            if not column_name:
                continue
            ordered_indexes[index_name].append(column_name)

        for name, columns in ordered_indexes.items():
            _register_structure("index", name, columns)

        legacy_targets = [
            (kind, name)
            for kind, name, columns in unique_structures
            if columns == legacy_columns
        ]
        has_desired = any(columns == desired_columns for _, _, columns in unique_structures)

    if legacy_targets and all(name is None for _, name in legacy_targets):
        if dialect == "sqlite":
            _rebuild_sqlite_session_table(engine)
            return

    statements: list[str] = []
    mysql_recreated = False

    def _drop_index(name: str) -> None:
        if dialect == "mysql":
            statements.append(
                f"ALTER TABLE session DROP INDEX {_quote_mysql_identifier(name)}"
            )
        elif dialect in {"postgresql", "sqlite"}:
            statements.append(f"DROP INDEX IF EXISTS {name}")
        else:
            statements.append(f"DROP INDEX {name}")

    def _drop_constraint(name: str) -> None:
        if dialect == "mysql":
            statements.append(
                f"ALTER TABLE session DROP INDEX {_quote_mysql_identifier(name)}"
            )
        elif dialect == "postgresql":
            statements.append(f"ALTER TABLE session DROP CONSTRAINT IF EXISTS {name}")
        else:
            statements.append(f"ALTER TABLE session DROP CONSTRAINT {name}")

    for kind, name in legacy_targets:
        if not name:
            continue
        if dialect == "mysql" and name == "uq_class_start_time":
            statements.append(
                "ALTER TABLE session DROP INDEX `uq_class_start_time`, "
                "ADD UNIQUE INDEX `uq_class_start_time` "
                "(class_group_id, subgroup_label, start_time)"
            )
            mysql_recreated = True
            continue
        if kind == "index":
            _drop_index(name)
        else:
            _drop_constraint(name)

    if not has_desired and not mysql_recreated:
        if dialect == "mysql":
            statements.append(
                "ALTER TABLE session ADD UNIQUE INDEX "
                "uq_class_start_time (class_group_id, subgroup_label, start_time)"
            )
        elif dialect == "postgresql":
            statements.append(
                "ALTER TABLE session ADD CONSTRAINT uq_class_start_time UNIQUE "
                "(class_group_id, subgroup_label, start_time)"
            )
        elif dialect == "sqlite":
            statements.append(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_class_start_time ON session "
                "(class_group_id, subgroup_label, start_time)"
            )
        else:
            statements.append(
                "ALTER TABLE session ADD CONSTRAINT uq_class_start_time UNIQUE "
                "(class_group_id, subgroup_label, start_time)"
            )

    if not statements:
        return

    try:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning(
            "Unable to realign session subgroup uniqueness constraint: %s", exc
        )


def _rebuild_sqlite_session_table(engine) -> None:
    """Rebuild the session table with the desired unique constraint on SQLite."""

    from .models import Session

    temp_table = "session_legacy_backup"

    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        renamed = False
        try:
            legacy_columns = [
                row["name"]
                for row in connection.execute(
                    text("PRAGMA table_info('session')")
                ).mappings()
            ]
            if not legacy_columns:
                return

            connection.execute(text(f"ALTER TABLE session RENAME TO {temp_table}"))
            renamed = True

            Session.__table__.create(bind=connection)

            current_columns = [column.name for column in Session.__table__.columns]
            transferable = [
                column
                for column in current_columns
                if column in legacy_columns
            ]

            if transferable:
                column_list = ", ".join(transferable)
                connection.execute(
                    text(
                        f"INSERT INTO session ({column_list}) "
                        f"SELECT {column_list} FROM {temp_table}"
                    )
                )

            connection.execute(text(f"DROP TABLE {temp_table}"))
        except SQLAlchemyError:
            if renamed:
                connection.execute(text(f"ALTER TABLE {temp_table} RENAME TO session"))
            raise
        finally:
            connection.execute(text("PRAGMA foreign_keys=ON"))

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


def _ensure_course_allowed_week_sessions_column() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "course_allowed_week" not in inspector.get_table_names():
        return

    existing_columns = {
        column["name"] for column in inspector.get_columns("course_allowed_week")
    }
    if "sessions_target" in existing_columns:
        return

    try:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE course_allowed_week ADD COLUMN sessions_target INTEGER")
            )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning(
            "Unable to add sessions_target column to course_allowed_week: %s",
            exc,
        )


def _ensure_course_color_column() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "course" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("course")}
    if "color" in existing_columns:
        return

    try:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE course ADD COLUMN color VARCHAR(7)"))
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard
        current_app.logger.warning("Unable to add color column to course: %s", exc)


def _ensure_student_profile_columns() -> None:
    engine = db.engine
    inspector = inspect(engine)
    if "student" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("student")}
    statements: list[tuple[str, str]] = []

    def queue(column_name: str, statement: str) -> None:
        if column_name not in existing_columns:
            statements.append((column_name, statement))

    queue(
        "full_name",
        "ALTER TABLE student ADD COLUMN full_name VARCHAR(200)",
    )
    queue("group_label", "ALTER TABLE student ADD COLUMN group_label VARCHAR(50)")
    queue("phase", "ALTER TABLE student ADD COLUMN phase VARCHAR(50)")
    queue(
        "pathway",
        "ALTER TABLE student ADD COLUMN pathway VARCHAR(20) NOT NULL DEFAULT 'initial'",
    )
    queue(
        "alternance_details",
        "ALTER TABLE student ADD COLUMN alternance_details TEXT",
    )
    queue("ina_id", "ALTER TABLE student ADD COLUMN ina_id VARCHAR(50)")
    queue("ub_id", "ALTER TABLE student ADD COLUMN ub_id VARCHAR(50)")
    queue("notes", "ALTER TABLE student ADD COLUMN notes TEXT")

    if not statements:
        return

    added_columns = {name for name, _ in statements}

    try:
        with engine.begin() as connection:
            for _, statement in statements:
                connection.execute(text(statement))
    except SQLAlchemyError as exc:  # pragma: no cover - defensive guard for legacy DBs
        current_app.logger.warning("Unable to update student table columns: %s", exc)
        return

    if "full_name" in added_columns:
        try:
            with engine.begin() as connection:
                if "name" in existing_columns:
                    connection.execute(
                        text(
                            "UPDATE student SET full_name = name "
                            "WHERE (full_name IS NULL OR full_name = '') "
                            "AND name IS NOT NULL AND name != ''"
                        )
                    )
                if {"first_name", "last_name"}.issubset(existing_columns):
                    rows = connection.execute(
                        text("SELECT id, first_name, last_name FROM student")
                    ).mappings()
                    for row in rows:
                        first = (row.get("first_name") or "").strip()
                        last = (row.get("last_name") or "").strip()
                        combined = " ".join(part for part in (first, last) if part).strip()
                        if not combined:
                            continue
                        connection.execute(
                            text(
                                "UPDATE student SET full_name = :full_name WHERE id = :id"
                            ),
                            {"full_name": combined, "id": row["id"]},
                        )
                missing = connection.execute(
                    text(
                        "SELECT id FROM student WHERE full_name IS NULL OR full_name = ''"
                    )
                ).mappings()
                for row in missing:
                    placeholder = f"Étudiant {row['id']}"
                    connection.execute(
                        text(
                            "UPDATE student SET full_name = :full_name WHERE id = :id"
                        ),
                        {"full_name": placeholder, "id": row["id"]},
                    )
        except SQLAlchemyError:
            current_app.logger.warning(
                "Unable to backfill student.full_name; continuing with placeholder-safe column."
            )

    if "pathway" in added_columns:
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE student SET pathway = :default "
                        "WHERE pathway IS NULL OR pathway = ''"
                    ),
                    {"default": "initial"},
                )
        except SQLAlchemyError:
            current_app.logger.warning(
                "Unable to backfill student.pathway with default values; continuing with partial data."
            )

        if engine.dialect.name not in {"sqlite"}:
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "ALTER TABLE student MODIFY pathway VARCHAR(20) NOT NULL DEFAULT 'initial'"
                        )
                    )
            except SQLAlchemyError:
                current_app.logger.warning(
                    "Unable to tighten constraints on student.pathway; continuing with relaxed column."
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

