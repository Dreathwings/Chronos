from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

from django.conf import settings
from django.contrib import messages
from django.http import (  # type: ignore
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_http_methods


_current_app: ContextVar[Any | None] = ContextVar("chronos_current_app", default=None)
_current_request: ContextVar["FlaskRequest" | None] = ContextVar(
    "chronos_current_request", default=None
)
_current_blueprint: ContextVar["Blueprint" | None] = ContextVar(
    "chronos_current_blueprint", default=None
)
_application: Any | None = None
_session_cleanup: Callable[[], None] | None = None


class _AppProxy:
    def _get_current_object(self) -> Any:
        app = _current_app.get()
        if app is None:
            raise RuntimeError("Working outside of application context.")
        return app

    def __getattr__(self, item: str) -> Any:
        app = _current_app.get()
        if app is None:
            raise AttributeError(item)
        return getattr(app, item)


class _RequestProxy:
    def _get_current_object(self) -> "FlaskRequest":
        req = _current_request.get()
        if req is None:
            raise RuntimeError("Working outside of request context.")
        return req

    def __getattr__(self, item: str) -> Any:
        req = _current_request.get()
        if req is None:
            raise AttributeError(item)
        return getattr(req, item)


current_app = _AppProxy()
request = _RequestProxy()


def push_app_context(app: Any) -> ContextVar[Any | None]:
    return _current_app.set(app)


def pop_app_context(token: ContextVar[Any | None]) -> None:
    _current_app.reset(token)


def push_request_context(django_request: HttpRequest) -> ContextVar[FlaskRequest | None]:
    return _current_request.set(FlaskRequest(django_request))


def pop_request_context(token: ContextVar[FlaskRequest | None]) -> None:
    _current_request.reset(token)


def push_blueprint_context(blueprint: "Blueprint") -> ContextVar[Blueprint | None]:
    return _current_blueprint.set(blueprint)


def pop_blueprint_context(token: ContextVar[Blueprint | None]) -> None:
    _current_blueprint.reset(token)


def init_application(app: Any) -> None:
    global _application
    _application = app


def get_application() -> Any | None:
    return _application


def register_session_cleanup(callback: Callable[[], None]) -> None:
    global _session_cleanup
    _session_cleanup = callback


class MultiDict:
    def __init__(self, data: Any) -> None:
        self._data = data

    def get(self, key: str, default: Any | None = None) -> Any | None:
        return self._data.get(key, default)

    def getlist(self, key: str) -> list[Any]:
        return list(self._data.getlist(key))

    def __getitem__(self, key: str) -> Any:
        if key not in self._data:
            raise KeyError(key)
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data


class Headers:
    def __init__(self, request: HttpRequest) -> None:
        self._request = request

    def get(self, key: str, default: Any | None = None) -> Any | None:
        normalized = key.upper().replace("-", "_")
        if normalized in {"CONTENT_TYPE", "CONTENT_LENGTH"}:
            meta_key = normalized
        else:
            meta_key = f"HTTP_{normalized}"
        return self._request.META.get(meta_key, default)

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None


class AcceptMimetypes:
    def __init__(self, header_value: str | None) -> None:
        self._qualities: dict[str, float] = {}
        if header_value:
            for item in header_value.split(","):
                token = item.strip()
                if not token:
                    continue
                mime, _, quality = token.partition(";q=")
                try:
                    score = float(quality) if quality else 1.0
                except ValueError:
                    score = 1.0
                mime = mime.strip()
                if mime == "*/*":
                    self._qualities.setdefault("text/html", score)
                else:
                    self._qualities[mime] = score
        else:
            self._qualities.setdefault("text/html", 1.0)

    def __bool__(self) -> bool:
        return bool(self._qualities)

    def __getitem__(self, key: str) -> float:
        return self._qualities.get(key, 0.0)

    @property
    def best(self) -> str | None:
        if not self._qualities:
            return None
        return max(self._qualities.items(), key=lambda item: item[1])[0]


class FlaskRequest:
    def __init__(self, django_request: HttpRequest) -> None:
        self._django_request = django_request
        self.method = django_request.method
        self.form = MultiDict(django_request.POST)
        self.args = MultiDict(django_request.GET)
        self.headers = Headers(django_request)

    @property
    def django_request(self) -> HttpRequest:
        return self._django_request

    @property
    def is_json(self) -> bool:
        content_type = self.headers.get("Content-Type", "") or ""
        return "json" in content_type.lower()

    @property
    def accept_mimetypes(self) -> AcceptMimetypes:
        return AcceptMimetypes(self.headers.get("Accept"))

    def get_json(self, silent: bool = False) -> Any:
        try:
            if not self._django_request.body:
                return None
            return json.loads(self._django_request.body.decode(self._django_request.encoding or "utf-8"))
        except Exception:
            if silent:
                return None
            raise

    @property
    def headers_dict(self) -> dict[str, Any]:
        return {
            key[5:].replace("_", "-"): value
            for key, value in self._django_request.META.items()
            if key.startswith("HTTP_")
        }


@dataclass
class RouteDefinition:
    rule: str
    methods: list[str]
    view_func: Callable[..., Any]
    endpoint: str


class Blueprint:
    def __init__(self, name: str, import_name: str) -> None:
        self.name = name
        self.import_name = import_name
        self.routes: list[RouteDefinition] = []
        self.context_processors: list[Callable[[], dict[str, Any]]] = []

    def route(self, rule: str, methods: Sequence[str] | None = None, **_: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        allowed = [method.upper() for method in (methods or ["GET"])]
        if "GET" in allowed and "HEAD" not in allowed:
            allowed.append("HEAD")

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            endpoint = func.__name__
            self.routes.append(RouteDefinition(rule, list(allowed), func, endpoint))
            return func

        return decorator

    def get(self, rule: str, **options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        return self.route(rule, methods=["GET"], **options)

    def app_context_processor(self, func: Callable[[], dict[str, Any]]) -> Callable[[], dict[str, Any]]:
        self.context_processors.append(func)
        return func


def jsonify(value: Any, status: int | None = None) -> JsonResponse:
    response = JsonResponse(value, safe=not isinstance(value, list))
    if status is not None:
        response.status_code = status
    return response


def flash(message: str, category: str = "message") -> None:
    req = _current_request.get()
    if req is None:
        raise RuntimeError("Flash messages require an active request context.")
    level = {
        "message": messages.INFO,
        "info": messages.INFO,
        "success": messages.SUCCESS,
        "warning": messages.WARNING,
        "danger": messages.ERROR,
        "error": messages.ERROR,
    }.get(category, messages.INFO)
    messages.add_message(req.django_request, level, message)


def get_flashed_messages(with_categories: bool = False) -> list[Any]:
    req = _current_request.get()
    if req is None:
        return []
    storage = list(messages.get_messages(req.django_request))
    rendered = [str(message) for message in storage]
    if not with_categories:
        return rendered
    category_map = {
        messages.INFO: "info",
        messages.SUCCESS: "success",
        messages.WARNING: "warning",
        messages.ERROR: "danger",
        messages.DEBUG: "debug",
    }
    return [
        (category_map.get(message.level, "info"), text)
        for message, text in zip(storage, rendered, strict=False)
    ]


def url_for(endpoint: str, **values: Any) -> str:
    if endpoint == "static":
        filename = values.get("filename", "")
        base = settings.STATIC_URL
        if not base.endswith("/"):
            base += "/"
        return f"{base}{filename}"
    if endpoint.startswith("."):
        blueprint = _current_blueprint.get()
        if blueprint is None:
            raise RuntimeError("Relative endpoint requires active blueprint context.")
        endpoint = f"{blueprint.name}{endpoint}"
    return reverse(endpoint, kwargs=values or None)


def render_template(template_name: str, **context: Any) -> HttpResponse:
    req = _current_request.get()
    if req is None:
        raise RuntimeError("Rendering templates requires an active request context.")
    combined: dict[str, Any] = {"url_for": url_for, "get_flashed_messages": get_flashed_messages}
    blueprint = _current_blueprint.get()
    if blueprint is not None:
        for processor in blueprint.context_processors:
            combined.update(processor())
    combined.update(context)
    return render(req.django_request, template_name, combined)


def redirect(location: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(location)


def _convert_rule(rule: str) -> str:
    cleaned = rule.lstrip("/")
    if not cleaned:
        return ""
    parts: list[str] = []
    for segment in cleaned.split("/"):
        if segment.startswith("<") and segment.endswith(">"):
            inner = segment[1:-1]
            if ":" in inner:
                type_name, var_name = inner.split(":", 1)
            else:
                type_name, var_name = "string", inner
            converter = {"int": "int", "string": "str"}.get(type_name, "str")
            parts.append(f"<{converter}:{var_name}>")
        else:
            parts.append(segment)
    return "/".join(parts)


def _convert_result(result: Any) -> HttpResponse:
    if isinstance(result, HttpResponse):
        return result
    if isinstance(result, tuple):
        response, status = result
        http_response = _convert_result(response)
        http_response.status_code = status
        return http_response
    if isinstance(result, (dict, list)):
        return JsonResponse(result, safe=not isinstance(result, list))
    if result is None:
        response = HttpResponse("")
        response.status_code = 204
        return response
    return HttpResponse(str(result))


def _build_view(blueprint: Blueprint, route: RouteDefinition) -> Callable[[HttpRequest, Any], HttpResponse]:
    allowed = route.methods

    def django_view(django_request: HttpRequest, **kwargs: Any) -> HttpResponse:
        if _application is None:
            raise RuntimeError("Chronos application has not been initialised.")
        token_app = push_app_context(_application)
        token_blueprint = push_blueprint_context(blueprint)
        try:
            result = route.view_func(**kwargs)
            response = _convert_result(result)
        except Http404:
            raise
        finally:
            if _session_cleanup is not None:
                _session_cleanup()
            pop_blueprint_context(token_blueprint)
            pop_app_context(token_app)
        return response

    return require_http_methods(allowed)(django_view)


def blueprint_to_urlpatterns(blueprint: Blueprint) -> list[Any]:
    patterns: list[Any] = []
    for route in blueprint.routes:
        django_path = _convert_rule(route.rule)
        view = _build_view(blueprint, route)
        name = f"{blueprint.name}.{route.endpoint}"
        patterns.append((django_path, view, name))
    from django.urls import path

    return [path(pattern or "", view, name=name) for pattern, view, name in patterns]
