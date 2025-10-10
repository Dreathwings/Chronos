from sqlalchemy import Table, Column, Integer, ForeignKey

from .. import db

session_enseignant = Table(
    "session_enseignant",
    db.Model.metadata,
    Column("session_id", Integer, ForeignKey("session.id", ondelete="CASCADE"), primary_key=True),
    Column("enseignant_id", Integer, ForeignKey("enseignant.id", ondelete="CASCADE"), primary_key=True),
)
