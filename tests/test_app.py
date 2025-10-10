from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Teacher


def test_index_route(tmp_path):
    cfg = Config(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path/'test.db'}",
        SECRET_KEY="test",
    )
    app = create_app(cfg)
    app.config.update({"TESTING": True})

    with app.app_context():
        db.create_all()
        teacher = Teacher(full_name="Test", email="test@example.com")
        db.session.add(teacher)
        db.session.commit()

    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
    assert b"Test" in response.data
