import os
import hmac
import secrets
import logging
from typing import Optional, Dict, Set
from fastapi import Request, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader

logger = logging.getLogger("iris.security.auth")

# Public endpoint paths that bypass authentication
PUBLIC_PATHS: Set[str] = {
    "/health",
    "/health/live",
    "/health/ready",
    "/health/liveness",
    "/health/readiness",
    "/health/detailed",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
}

http_bearer = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class AuthManager:
    """
    Manages API keys, bearer tokens, and per-device tokens.
    Rejects default trivial keys and generates a secure random token if unconfigured.
    """

    def __init__(self, master_key: Optional[str] = None):
        key = (
            master_key
            or os.getenv("IRIS_API_KEY")
            or os.getenv("IRIS_MASTER_TOKEN")
        )
        if not key or key.lower() in ("ollama", "default", "secret", "password", "admin", "123456"):
            key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
            if not key or key.lower() in ("ollama", "default", "secret", "password", "admin", "123456"):
                key = secrets.token_hex(32)
                logger.info("No master token configured. Generated secure random token for startup.")
        self.master_key = key
        self.device_tokens: Dict[str, str] = {}  # device_id -> token

    def register_device_token(self, device_id: str, token: str):
        self.device_tokens[device_id] = token

    def validate_token(self, token: Optional[str], device_id: Optional[str] = None) -> bool:
        if not token:
            return False

        # 1. Compare against master key
        if hmac.compare_digest(token, self.master_key):
            return True

        # 2. Compare against device specific token if provided
        if device_id and device_id in self.device_tokens:
            if hmac.compare_digest(token, self.device_tokens[device_id]):
                return True

        # 3. Check any registered device token
        for registered_token in self.device_tokens.values():
            if hmac.compare_digest(token, registered_token):
                return True

        return False


# Global AuthManager instance
auth_manager = AuthManager()


async def verify_api_key(
    request: Request,
    bearer: Optional[HTTPAuthorizationCredentials] = Security(http_bearer),
    api_key_h: Optional[str] = Security(api_key_header),
) -> str:
    """
    FastAPI dependency that enforces API key or Bearer token authentication.
    """
    path = request.url.path
    if path in PUBLIC_PATHS or path.rstrip("/") in PUBLIC_PATHS:
        return "public"

    # Extract token from Bearer header, X-API-Key header, or query params
    token = None
    if bearer and bearer.credentials:
        token = bearer.credentials
    elif api_key_h:
        token = api_key_h
    else:
        token = request.query_params.get("token") or request.query_params.get("api_key")

    device_id = request.query_params.get("device_id") or request.headers.get("X-Device-ID")

    if not token or not auth_manager.validate_token(token, device_id=device_id):
        logger.warning(f"Unauthorized request to '{path}' from IP {request.client.host if request.client else 'unknown'}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token
