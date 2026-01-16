import pytest

from app import create_app, db
from config import TestConfig


@pytest.fixture()
def app():
    app = create_app(TestConfig)
    ctx = app.app_context()
    ctx.push()
    db.create_all()
    yield app
    db.session.remove()
    db.drop_all()
    ctx.pop()


@pytest.fixture()
def session(app):
    return db.session
