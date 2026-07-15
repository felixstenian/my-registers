import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Injeta X-Request-Id e loga latência."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "request_error",
                extra={
                    "request_id": request_id,
                    "route": request.url.path,
                    "latency_ms": latency_ms,
                    "event": "http_request",
                },
            )
            raise
        latency_ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "http_request",
            extra={
                "request_id": request_id,
                "route": request.url.path,
                "latency_ms": latency_ms,
                "event": "http_request",
            },
        )
        return response
