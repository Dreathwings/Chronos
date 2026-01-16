from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date
from typing import Iterable

from flask import current_app

from app import db
from app.models import Course, CourseScheduleLog, Session


def suggest_schedule_recovery(message: str, course: Course | None = None) -> list[str]:
    text = (message or "").lower()
    suggestions: list[str] = []

    def add(option: str) -> None:
        cleaned = option.strip()
        if cleaned and cleaned not in suggestions:
            suggestions.append(cleaned)

    if "associez au moins une classe" in text:
        add("Associez une ou plusieurs classes au cours depuis sa fiche avant de relancer la génération.")
    if "aucun enseignant n'est associé" in text:
        add("Affectez un enseignant au cours ou au lien classe ↔ cours pour disposer d'intervenants disponibles.")
    if "aucun enseignant disponible" in text or "est déjà planifié" in text:
        add("Élargissez les disponibilités des enseignants ou libérez leurs créneaux en déplaçant des séances existantes.")
    if "aucune salle n'est enregistrée" in text:
        add("Créez au moins une salle compatible dans la section Salles.")
    if "aucune salle n'atteint la capacité" in text:
        add("Ajoutez une salle plus grande ou répartissez la classe en sous-groupes pour réduire la capacité nécessaire.")
    if "postes informatiques" in text or "ordinateur" in text:
        add("Augmentez le nombre de postes informatiques disponibles ou assouplissez l'exigence d'ordinateurs pour ce cours.")
    if "équipement requis" in text:
        add("Associez les équipements requis à une salle ou retirez l'exigence côté cours si elle n'est plus nécessaire.")
    if "aucune salle compatible n'est disponible" in text:
        add("Libérez des créneaux de salles occupées ou autorisez d'autres salles répondant aux contraintes du cours.")
    if "aucune journée" in text and "disponible" in text:
        add("Élargissez la fenêtre de planification ou assouplissez les indisponibilités des classes concernées.")
    if "les semaines sélectionnées ne recoupent pas la fenêtre" in text:
        add("Modifiez les semaines autorisées du cours pour qu'elles recouvrent la période définie.")
    if "semaines sélectionnées correspondent uniquement à des périodes de fermeture" in text or "fenêtre de planification est entièrement couverte" in text:
        add("Retirez les semaines de fermeture des contraintes ou décalez les dates du cours hors des périodes de congés.")
    if "période de planification n'est définie" in text:
        add("Renseignez les dates de début et de fin du cours pour le semestre actuel.")
    if "durée hebdomadaire autorisée" in text:
        add("Répartissez les heures sur plus de semaines ou réduisez le volume demandé chaque semaine.")
    if "chronologie cm" in text:
        add("Réorganisez les séances CM/TD/TP existantes afin de respecter l'ordre hebdomadaire imposé.")
    if "impossible de planifier" in text:
        add("Planifiez manuellement les dernières séances ou détendez les contraintes sur les disponibilités et les ressources.")

    if course is not None:
        if not course.teachers:
            add("Associez au moins un enseignant au cours pour permettre la planification automatique.")
        if not course.classes:
            add("Associez une classe au cours avant de lancer la génération automatique.")

    if not suggestions:
        add("Essayez de planifier manuellement la séance depuis la fiche du cours ou ajustez les contraintes concernées.")

    return suggestions


class ScheduleReporter:
    MAX_DETAILED_ENTRIES = 50
    MAX_TOTAL_ENTRIES = 120
    LEVELS = {
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }

    def __init__(
        self,
        course: Course,
        *,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> None:
        self.course = course
        self.window_start = window_start
        self.window_end = window_end
        self.entries: list[dict[str, object]] = []
        self.status = "success"
        self.summary: str | None = None
        self._finalised = False
        self._record: CourseScheduleLog | None = None

    def set_window(self, start: date, end: date) -> None:
        self.window_start = start
        self.window_end = end
        self.info(f"Fenêtre de planification : {start} → {end}")

    def info(self, message: str, *, suggestions: Iterable[str] | None = None) -> None:
        self._add_entry("info", message, suggestions=suggestions)

    def warning(self, message: str, *, suggestions: Iterable[str] | None = None) -> None:
        self._add_entry("warning", message, suggestions=suggestions)
        if self.status != "error":
            self.status = "warning"

    def error(self, message: str, *, suggestions: Iterable[str] | None = None) -> None:
        self._add_entry("error", message, suggestions=suggestions)
        self.status = "error"

    def session_created(self, session: Session) -> None:
        start_label = session.start_time.strftime("%d/%m/%Y %H:%M")
        end_label = session.end_time.strftime("%H:%M")
        attendees = ", ".join(session.attendee_names())
        teacher_name = session.teacher.name if session.teacher else "Aucun enseignant"
        room_name = session.room.name if session.room else "Aucune salle"
        duration = session.duration_hours
        self.info(
            f"Séance planifiée le {start_label} → {end_label} ({duration} h)"
            f" — {attendees} avec {teacher_name} en salle {room_name}"
        )

    def finalise(self, created_count: int) -> CourseScheduleLog:
        if self._finalised and self._record is not None:
            return self._record
        if self.summary is None:
            if created_count:
                if self.status == "success":
                    self.summary = f"{created_count} séance(s) générée(s)"
                else:
                    self.summary = (
                        f"{created_count} séance(s) générée(s) avec avertissements"
                    )
            else:
                if self.status == "success":
                    self.summary = "Aucune séance générée"
                else:
                    self.summary = "Aucune séance générée — vérifier les avertissements"

        log = CourseScheduleLog(
            course=self.course,
            status=self.status,
            summary=self.summary,
            messages=json.dumps(self._serialise_entries(), ensure_ascii=False),
            window_start=self.window_start,
            window_end=self.window_end,
        )
        db.session.add(log)
        self._finalised = True
        self._record = log
        return log

    def _add_entry(
        self, level: str, message: str, *, suggestions: Iterable[str] | None = None
    ) -> None:
        text = message.strip()
        if not text:
            return
        if level == "error":
            entry: dict[str, object] = {"level": level, "message": text}
            if suggestions:
                unique_suggestions: list[str] = []
                for suggestion in suggestions:
                    cleaned = str(suggestion).strip()
                    if cleaned and cleaned not in unique_suggestions:
                        unique_suggestions.append(cleaned)
                if unique_suggestions:
                    entry["suggestions"] = unique_suggestions
            self.entries.append(entry)
        logger = getattr(current_app, "logger", None)
        if logger is not None:
            log_level = self.LEVELS.get(level, logging.INFO)
            logger.log(log_level, "[%s] %s", self.course.name, text)

    def _serialise_entries(self) -> list[dict[str, object]]:
        if not self.entries:
            return []
        if len(self.entries) <= self.MAX_DETAILED_ENTRIES:
            return [dict(entry) for entry in self.entries]

        detailed = [dict(entry) for entry in self.entries[: self.MAX_DETAILED_ENTRIES]]
        summary_counts: dict[tuple[str, str], int] = {}
        summary_order: list[tuple[str, str]] = []
        for entry in self.entries[self.MAX_DETAILED_ENTRIES :]:
            key = (entry["level"], entry["message"])
            if key not in summary_counts:
                summary_counts[key] = 0
                summary_order.append(key)
            summary_counts[key] += 1

        for level, message in summary_order:
            count = summary_counts[(level, message)]
            if count > 1:
                label = f"{message} (résumé {count}×)"
            else:
                label = f"{message} (résumé)"
            detailed.append({"level": level, "message": label})
            if len(detailed) >= self.MAX_TOTAL_ENTRIES:
                break
        return detailed[: self.MAX_TOTAL_ENTRIES]


def summarise_constraint_reasons(reason_counts: Counter[str]) -> list[str]:
    if not reason_counts:
        return []
    return [f"{reason} ({count})" for reason, count in reason_counts.most_common(3)]
