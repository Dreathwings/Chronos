from __future__ import annotations

from typing import Callable

from django.http import HttpRequest, HttpResponse

from .flask_compat import pop_request_context, push_request_context


class ChronosRequestMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        token = push_request_context(request)
        try:
            response = self.get_response(request)
        finally:
            pop_request_context(token)
        return response
