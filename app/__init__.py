from flask import Flask, current_app
from flask.cli import with_appcontext
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from config import Config


db = SQLAlchemy()
migrate = Migrate()


def create_app(config_class: type[Config] = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401  # Ensure models registered for migrations

    with app.app_context():
        db.create_all()
        _ensure_session_class_group_column()
        _ensure_session_subgroup_column()
        _ensure_course_class_group_count_column()
        _ensure_course_class_teacher_columns()
        _ensure_course_type_column()

    from .routes import bp as main_bp

    app.register_blueprint(main_bp)

    @app.cli.command("seed")
    @with_appcontext
    def seed() -> None:
        """Seed initial data for development."""
        from .seed import seed_data

        seed_data()
        print("Database seeded with sample data.")

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
                    "ALTER TABLE course ADD COLUMN course_type VARCHAR(2) NOT NULL DEFAULT 'CM'"
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
                        "ALTER TABLE course MODIFY course_type VARCHAR(2) NOT NULL DEFAULT 'CM'"
                    )
                )
        except SQLAlchemyError:
            current_app.logger.warning(
                "Unable to tighten constraints on course.course_type; continuing with relaxed column."
            )
