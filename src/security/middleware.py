import time
import logging
from typing import Dict, List, Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from fastapi import status

logger = logging.getLogger("iris.security.middleware")


class SlidingWindowRateLimiter:
    """
    In-memory sliding-window rate limiter per client IP or device_id.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: Dict[str, List[float]] = {}  # key -> timestamp list

    def is_rate_limited(self, key: str) -> tuple[bool, int]:
        now = time.time()
        window_start = now - self.window_seconds

        if key not in self.requests:
            self.requests[key] = []

        # Filter out timestamps outside the sliding window
        self.requests[key] = [t for t in self.requests[key] if t > window_start]

        if len(self.requests[key]) >= self.max_requests:
            oldest = self.requests[key][0]
            retry_after = int(oldest + self.window_seconds - now) + 1
            return True, max(1, retry_after)

        self.requests[key].append(now)
        return False, 0


# Global rate limiter instance
global_rate_limiter = SlidingWindowRateLimiter(max_requests=60, window_seconds=60)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Applies security response headers to all outgoing HTTP responses.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Applies sliding-window rate limiting per client IP or device_id.
    Exempts health and metrics endpoints.
    """

    def __init__(self, app, rate_limiter: Optional[SlidingWindowRateLimiter] = None):
        super().__init__(app)
        self.rate_limiter = rate_limiter or global_rate_limiter

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if path in {"/health", "/health/live", "/health/ready", "/health/liveness", "/health/readiness", "/health/detailed", "/metrics"}:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        device_id = request.headers.get("X-Device-ID") or request.query_params.get("device_id")
        rate_key = f"{device_id}_{client_ip}" if device_id else client_ip

        limited, retry_after = self.rate_limiter.is_rate_limited(rate_key)
        if limited:
            logger.warning(f"Rate limit exceeded for key '{rate_key}' on path '{path}'. Retry after {retry_after}s.")
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": "Too Many Requests", "message": f"Rate limit exceeded. Try again in {retry_after} seconds."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


class RequestSizeLimiterMiddleware(BaseHTTPMiddleware):
    """
    Rejects incoming requests exceeding maximum payload size limits.
    """

    def __init__(self, app, max_json_bytes: int = 1 * 1024 * 1024, max_audio_bytes: int = 10 * 1024 * 1024):
        super().__init__(app)
        self.max_json_bytes = max_json_bytes
        self.max_audio_bytes = max_audio_bytes

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        content_type = request.headers.get("content-type", "")

        if content_length:
            try:
                length = int(content_length)
                max_allowed = self.max_audio_bytes if ("multipart" in content_type or "audio" in content_type) else self.max_json_bytes
                if length > max_allowed:
                    logger.warning(f"Request payload of {length} bytes exceeded max size limit of {max_allowed} bytes.")
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={
                            "error": "Payload Too Large",
                            "message": f"Request size {length} bytes exceeds maximum allowed threshold of {max_allowed} bytes."
                        }
                    )
            except ValueError:
                pass

        return await call_next(request)
