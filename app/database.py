from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import scoped_session, sessionmaker


SessionFactory = scoped_session


def init_engine(url: str, *, echo: bool = False) -> Engine:
    return create_engine(url, echo=echo, future=True)


def init_session_factory(engine: Engine) -> SessionFactory:
    return scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True))


@contextmanager
def session_scope(session_factory: SessionFactory):
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        session_factory.remove()
