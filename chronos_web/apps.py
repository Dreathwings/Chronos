from __future__ import annotations

from django.apps import AppConfig
from django.conf import settings

from app import create_app
from chronos_web.flask_compat import get_application, init_application


class ChronosWebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "chronos_web"

    def ready(self) -> None:  # pragma: no cover - called by Django
        if get_application() is None:
            app = create_app(settings.CONFIG)
            init_application(app)
