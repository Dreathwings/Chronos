from __future__ import annotations

import json
from functools import lru_cache
from typing import Iterable

from django.conf import settings
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup


def _template_directories() -> list[str]:
    directories: list[str] = []
    for engine in getattr(settings, "TEMPLATES", []):
        dirs: Iterable[str] = engine.get("DIRS", [])  # type: ignore[assignment]
        for path in dirs:
            if path and path not in directories:
                directories.append(path)
    # Ensure the legacy Flask template directory is always available.
    default_path = settings.BASE_DIR / "app" / "templates"
    default_str = str(default_path)
    if default_str not in directories:
        directories.append(default_str)
    return directories


@lru_cache(maxsize=1)
def get_environment() -> Environment:
    loader = FileSystemLoader(_template_directories())
    env = Environment(
        loader=loader,
        autoescape=select_autoescape(["html", "htm", "xml"]),
        enable_async=False,
        auto_reload=getattr(settings, "DEBUG", False),
    )

    def _tojson(value: object) -> Markup:
        return Markup(json.dumps(value, ensure_ascii=False))

    env.filters.setdefault("tojson", _tojson)
    return env

