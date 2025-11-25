from __future__ import annotations

from app.routes import bp
from .flask_compat import blueprint_to_urlpatterns

urlpatterns = blueprint_to_urlpatterns(bp)
