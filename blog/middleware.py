"""Safe HTTP access logs with a correlation ID for application events."""

import logging
from time import monotonic
from uuid import uuid4

from .logging import request_id


access_logger = logging.getLogger("blog.access")
HEALTH_PATHS = frozenset({"/healthz/", "/readyz/"})


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        correlation_id = uuid4().hex
        token = request_id.set(correlation_id)
        started = monotonic()
        response = None
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = correlation_id
            return response
        finally:
            try:
                status = getattr(response, "status_code", 500)
                if request.path_info not in HEALTH_PATHS or status >= 500:
                    match = getattr(request, "resolver_match", None)
                    route = getattr(match, "route", None)
                    # A route is a code-defined template, never a user-supplied URL.
                    route = "/" + route.lstrip("/") if route else ("/" if match else "unmatched")
                    log = (
                        access_logger.error if status >= 500 else
                        access_logger.warning if status >= 400 else access_logger.info
                    )
                    response_bytes = response.get("Content-Length", "-") if response else "-"
                    duration_ms = round((monotonic() - started) * 1000, 2)
                    log(
                        "http.request method=%s route=%s status=%s duration_ms=%.2f response_bytes=%s",
                        request.method, route, status, duration_ms,
                        response_bytes,
                        extra={
                            "method": request.method,
                            "route": route,
                            "status": status,
                            "duration_ms": duration_ms,
                            "response_bytes": int(response_bytes) if response_bytes.isdigit() else None,
                        },
                    )
            finally:
                request_id.reset(token)
