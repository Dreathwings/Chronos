from __future__ import annotations

from django.conf import settings
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path

prefix = (settings.CHRONOS_URL_PREFIX or "").strip("/")

if prefix:
    urlpatterns = [path(f"{prefix}/", include("chronos_web.urls"))]
else:
    urlpatterns = [path("", include("chronos_web.urls"))]

urlpatterns += staticfiles_urlpatterns()
