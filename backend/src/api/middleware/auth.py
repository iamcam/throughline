# src/api/middleware/auth.py
import base64
import logging
import secrets

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.config import get_settings

logger = logging.getLogger(__name__)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """
    HTTP Basic Auth middleware.
    Bypassed when DEMO_AUTH_ENABLED=false.
    Unprotected routes: /api/v1/health, /docs, /redoc, /openapi.json
    """

    UNPROTECTED = {"/api/v1/health", "/docs", "/redoc", "/openapi.json"}

    async def dispatch(self, request: Request, call_next) -> Response:
        settings = get_settings()

        if not settings.demo_auth_enabled:
            return await call_next(request)

        if request.url.path in self.UNPROTECTED:
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Podcast Knowledge Engine Demo"'},
                content="Authentication required",
            )

        try:
            credentials = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = credentials.split(":", 1)
        except Exception:
            return JSONResponse(status_code=401, content={"detail": "Invalid credentials"})

        valid_user = secrets.compare_digest(username, settings.demo_username)
        valid_pass = secrets.compare_digest(password, settings.demo_password)

        if not (valid_user and valid_pass):
            logger.warning("Failed auth attempt for username: %s", username)
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Podcast Knowledge Engine Demo"'},
                content="Invalid credentials",
            )

        return await call_next(request)