import os
import hmac
import time
import hashlib
import secrets
import logging
from typing import Optional, Dict, Set, Any
from dotenv import load_dotenv
load_dotenv()
from fastapi import Request, HTTPException, status, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials, APIKeyHeader

logger = logging.getLogger("iris.security.auth")

# Public endpoint paths that bypass authentication for basic health checks
PUBLIC_PATHS: Set[str] = {
    "/",
    "/dashboard",
    "/mobile",
    "/api/pairing/pair",
    "/pairing/pair",
    "/health",
    "/health/live",
    "/health/ready",
    "/health/liveness",
    "/health/readiness",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# Detailed telemetry and operational inspection paths (Loopback allowed or authenticated)
SENSITIVE_TELEMETRY_PATHS: Set[str] = {
    "/api/dashboard/status",
    "/health/detailed",
    "/metrics",
}

# Known public template/sample credentials that MUST be rejected in production
INSECURE_SAMPLE_KEYS: Set[str] = {
    "ollama", "default", "secret", "password", "admin", "123456",
    "iris-master-key-offline-2026", "iris_secret_token", "iris_master_token",
    "change-me", "your-master-token-here", "change-me-to-a-secure-random-token",
    "test", "testkey", "sample"
}

http_bearer = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class AuthManager:
    """
    Manages API keys, bearer tokens, and per-device tokens.
    Rejects default trivial keys, blocks known sample credentials,
    and generates a secure random token if unconfigured or insecure.
    """

    def __init__(self, master_key: Optional[str] = None):
        key = (
            master_key
            or os.getenv("IRIS_API_KEY")
            or os.getenv("IRIS_MASTER_TOKEN")
        )
        is_insecure = not key or key.strip().lower() in INSECURE_SAMPLE_KEYS

        if is_insecure:
            is_prod = os.getenv("IRIS_ENVIRONMENT", "local").lower() == "production"
            if is_prod:
                raise RuntimeError(
                    "SECURITY_ERROR: Insecure sample token detected in production. "
                    "Configure a unique IRIS_MASTER_TOKEN in your environment."
                )
            key = secrets.token_hex(32)
            logger.warning(
                "SECURITY_NOTICE: Insecure sample or empty master token detected. "
                "Generated secure random token for active runtime session."
            )

        self.master_key = key
        self.device_tokens: Dict[str, str] = {}  # device_id -> token
        self._plan_tokens: Dict[str, Dict[str, Any]] = {}  # plan_id -> metadata

    def get_master_key(self) -> str:
        """Return the active master key."""
        return self.master_key

    def register_device_token(self, device_id: str, token: str):
        self.device_tokens[device_id] = token

    def revoke_device_token(self, device_id: str) -> bool:
        return self.device_tokens.pop(device_id, None) is not None

    def create_plan_approval_token(self, plan_id: str, content_hash: str, ttl_sec: float = 300.0) -> str:
        """
        Creates a single-use approval token cryptographically bound to plan_id and content_hash.
        """
        raw = f"{plan_id}:{content_hash}:{secrets.token_hex(16)}"
        signature = hmac.new(self.master_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"pat_{signature[:32]}"
        self._plan_tokens[plan_id] = {
            "token": token,
            "content_hash": content_hash,
            "expires_at": time.time() + ttl_sec,
        }
        logger.info(f"Issued plan approval token for plan '{plan_id}' with digest {content_hash[:8]}...")
        return token

    def validate_plan_approval_token(self, plan_id: str, content_hash: str, token: Optional[str]) -> bool:
        """
        Validates and consumes a plan approval token.
        Requires exact match for plan_id, content_hash, non-expired TTL, and token value.
        """
        if not token or not token.strip():
            logger.warning(f"Plan approval token validation rejected: empty token for plan '{plan_id}'")
            return False
        clean_token = token.strip()
        record = self._plan_tokens.get(plan_id)
        if not record:
            logger.warning(f"Plan approval token validation rejected: no active token record for plan '{plan_id}'")
            return False
        if time.time() > record["expires_at"]:
            self._plan_tokens.pop(plan_id, None)
            logger.warning(f"Plan approval token validation rejected: token expired for plan '{plan_id}'")
            return False
        if not hmac.compare_digest(record["content_hash"], content_hash):
            logger.warning(f"Plan approval token validation rejected: content_hash mismatch for plan '{plan_id}'")
            return False
        if not hmac.compare_digest(record["token"], clean_token):
            logger.warning(f"Plan approval token validation rejected: token mismatch for plan '{plan_id}'")
            return False

        # Consumed on successful validation (single-use)
        self._plan_tokens.pop(plan_id, None)
        logger.info(f"Plan approval token successfully validated and consumed for plan '{plan_id}'")
        return True

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
    client_host = request.client.host if request.client else "unknown"
    is_loopback = client_host in ("127.0.0.1", "::1", "localhost", "testclient")

    # Sensitive telemetry endpoints are accessible without auth ONLY over loopback
    if (path in SENSITIVE_TELEMETRY_PATHS or path.rstrip("/") in SENSITIVE_TELEMETRY_PATHS) and is_loopback:
        return "loopback_telemetry"

    if (
        path in PUBLIC_PATHS 
        or path.rstrip("/") in PUBLIC_PATHS
        or path.startswith("/static")
        or path.startswith("/dashboard/static")
    ):
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
