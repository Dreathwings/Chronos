from __future__ import annotations

from typing import Any

from .flask_compat import get_flashed_messages, url_for


def inject_blueprint_context(request: Any) -> dict[str, Any]:  # pragma: no cover - template helper
    return {
        "url_for": url_for,
        "get_flashed_messages": get_flashed_messages,
    }
