from __future__ import annotations

from datetime import date

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DateField,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional


class TeacherForm(FlaskForm):
    full_name = StringField("Nom complet", validators=[DataRequired(), Length(max=120)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    max_hours_per_week = IntegerField(
        "Heures max/sem",
        validators=[DataRequired(), NumberRange(min=1, max=60)],
        default=20,
    )
    submit = SubmitField("Enregistrer")


class TeacherAvailabilityForm(FlaskForm):
    weekday = SelectField(
        "Jour",
        choices=[
            (0, "Lundi"),
            (1, "Mardi"),
            (2, "Mercredi"),
            (3, "Jeudi"),
            (4, "Vendredi"),
            (5, "Samedi"),
            (6, "Dimanche"),
        ],
        coerce=int,
        validators=[DataRequired()],
    )
    start_time = TimeField("Début", validators=[DataRequired()])
    end_time = TimeField("Fin", validators=[DataRequired()])
    submit = SubmitField("Ajouter la disponibilité")


class TeacherUnavailabilityForm(FlaskForm):
    date = DateField("Date", validators=[DataRequired()])
    reason = StringField("Motif", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Ajouter l'indisponibilité")


class RoomForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=80)])
    capacity = IntegerField("Capacité", validators=[DataRequired(), NumberRange(min=1)])
    computers = IntegerField("Postes informatiques", validators=[Optional(), NumberRange(min=0)])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=255)])
    materials = SelectMultipleField("Matériel", coerce=int)
    submit = SubmitField("Enregistrer")


class MaterialForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=120)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Enregistrer")


class SoftwareForm(FlaskForm):
    name = StringField("Nom", validators=[DataRequired(), Length(max=120)])
    version = StringField("Version", validators=[Optional(), Length(max=40)])
    submit = SubmitField("Enregistrer")


class CourseForm(FlaskForm):
    title = StringField("Titre", validators=[DataRequired(), Length(max=120)])
    duration_hours = IntegerField("Durée (h)", validators=[DataRequired(), NumberRange(min=1, max=8)])
    session_count = IntegerField("Nombre de séances", validators=[DataRequired(), NumberRange(min=1, max=20)])
    priority = IntegerField("Priorité", validators=[DataRequired(), NumberRange(min=1, max=5)], default=1)
    required_capacity = IntegerField(
        "Capacité requise",
        validators=[DataRequired(), NumberRange(min=1, max=500)],
        default=20,
    )
    requires_computers = BooleanField("Salle informatique requise")
    materials = SelectMultipleField("Matériel nécessaire", coerce=int)
    softwares = SelectMultipleField("Logiciels", coerce=int)
    submit = SubmitField("Enregistrer")


class SessionForm(FlaskForm):
    course_id = SelectField("Cours", coerce=int, validators=[DataRequired()])
    teacher_id = SelectField("Enseignant", coerce=int, validators=[DataRequired()])
    room_id = SelectField("Salle", coerce=int, validators=[DataRequired()])
    date = DateField("Date", validators=[DataRequired()], default=date.today)
    slot = SelectField("Créneau", validators=[DataRequired()])
    submit = SubmitField("Planifier")


class QuickPlanForm(FlaskForm):
    start_day = DateField("Date de début", validators=[Optional()])
    horizon_days = IntegerField(
        "Nombre de jours",
        validators=[DataRequired(), NumberRange(min=1, max=30)],
        default=5,
    )
    submit = SubmitField("Planification automatique")
