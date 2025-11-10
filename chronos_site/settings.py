from __future__ import annotations

import os
from pathlib import Path

from config import Config

BASE_DIR = Path(__file__).resolve().parent.parent

CONFIG = Config()

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", CONFIG.SECRET_KEY)
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS: list[str] = [host for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",") if host]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "chronos_web",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "chronos_web.middleware.ChronosRequestMiddleware",
]

ROOT_URLCONF = "chronos_site.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "app" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "chronos_web.context_processors.inject_blueprint_context",
            ],
        },
    }
]

WSGI_APPLICATION = "chronos_site.wsgi.application"
ASGI_APPLICATION = "chronos_site.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "chronos.sqlite3"),
    }
}

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Europe/Paris"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "app" / "static"]
STATIC_ROOT = os.environ.get("DJANGO_STATIC_ROOT", str(BASE_DIR / "static"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CHRONOS_URL_PREFIX = CONFIG.URL_PREFIX
SQLALCHEMY_DATABASE_URI = CONFIG.SQLALCHEMY_DATABASE_URI
