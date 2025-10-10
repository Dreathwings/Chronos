from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from flask import current_app
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def get_app_config():
    if current_app:
        return current_app.config
    raise RuntimeError("Flask application not available. Utiliser 'flask db' pour gérer les migrations.")

def run_migrations_offline() -> None:
    app_config = get_app_config()
    url = app_config["SQLALCHEMY_DATABASE_URI"]
    context.configure(url=url, target_metadata=current_app.extensions["migrate"].db.metadata, literal_binds=True)

    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online() -> None:
    app_config = get_app_config()
    alembic_config = config.get_section(config.config_ini_section)
    alembic_config["sqlalchemy.url"] = app_config["SQLALCHEMY_DATABASE_URI"]

    connectable = engine_from_config(
        alembic_config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    target_metadata = current_app.extensions["migrate"].db.metadata

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


def run_migrations() -> None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()


run_migrations()
