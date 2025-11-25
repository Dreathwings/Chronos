from __future__ import annotations

from typing import Any
import re

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    DeclarativeMeta,
    Query,
    as_declarative,
    scoped_session,
    sessionmaker,
)
from django.http import Http404


def _camel_to_snake(name: str) -> str:
    """Convert ``CamelCase`` to ``snake_case`` for implicit table names."""

    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class _ModelMeta(DeclarativeMeta):
    """Declarative metaclass that mimics Flask-SQLAlchemy defaults."""

    def __init__(cls, name, bases, dct, **kwargs):  # type: ignore[override]
        if not dct.get("__abstract__"):
            has_explicit_table = "__tablename__" in dct or "__table__" in dct
            inherits_table = any(
                getattr(base, "__mapper__", None) is not None for base in bases
            )
            if not has_explicit_table and not inherits_table:
                cls.__tablename__ = _camel_to_snake(name)
        super().__init__(name, bases, dct, **kwargs)


class BaseQuery(Query):
    def get_or_404(self, ident: Any) -> Any:
        instance = self.get(ident)
        if instance is None:
            raise Http404()
        return instance

    def first_or_404(self) -> Any:
        instance = self.first()
        if instance is None:
            raise Http404()
        return instance


@as_declarative(metaclass=_ModelMeta)
class Model:
    __abstract__ = True


class SQLAlchemy:
    def __init__(self) -> None:
        self.Model = Model
        self._engine = None
        self.session = None
        self.engine = None

    def init_app(self, app: Any) -> None:
        uri = app.config.get("SQLALCHEMY_DATABASE_URI")
        if not uri:
            raise RuntimeError("SQLAlchemy database URI is not configured.")
        self._engine = create_engine(uri, future=True)
        session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False, query_cls=BaseQuery
        )
        self.session = scoped_session(session_factory)
        self.Model.metadata.bind = self._engine
        self.Model.query = self.session.query_property()  # type: ignore[attr-defined]
        self.engine = self._engine

    def create_all(self) -> None:
        if self._engine is None:
            raise RuntimeError("Database engine has not been initialised.")
        self.Model.metadata.create_all(self._engine)

    def drop_all(self) -> None:
        if self._engine is None:
            raise RuntimeError("Database engine has not been initialised.")
        self.Model.metadata.drop_all(self._engine)

    def __getattr__(self, name: str) -> Any:
        """Proxy attribute access to :mod:`sqlalchemy` for column helpers."""

        try:
            value = getattr(sa, name)
        except AttributeError as exc:  # pragma: no cover - mirrors Flask-SQLAlchemy
            raise AttributeError(name) from exc
        setattr(self, name, value)
        return value
