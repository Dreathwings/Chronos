from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Query, scoped_session, sessionmaker
from sqlalchemy.orm import declarative_base
from django.http import Http404


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


class SQLAlchemy:
    def __init__(self) -> None:
        self.Model = declarative_base()
        self._engine = None
        self.session = None

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
