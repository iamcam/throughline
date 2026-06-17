# tests/unit/test_auth_middleware.py
import base64
import pytest
from unittest.mock import patch
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport

from src.api.middleware.auth import BasicAuthMiddleware
from src.config import Settings


def make_app(settings: Settings) -> FastAPI:
    """Build a minimal FastAPI app with auth middleware and test routes."""
    app = FastAPI()
    app.add_middleware(BasicAuthMiddleware)

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @app.get("/protected")
    async def protected():
        return {"data": "secret"}

    @app.get("/docs")
    async def docs():
        return {"docs": "ok"}

    return app


def make_settings(enabled: bool = True) -> Settings:
    return Settings(
        demo_auth_enabled=enabled,
        demo_username="testuser",
        demo_password="testpass",
        database_url="postgresql+asyncpg://x:x@localhost/x",
        cors_origins="http://localhost:3000",
        llm_base_url="http://localhost:11434/v1",
        llm_model_name="llama3",
    )


def basic_auth_header(username: str, password: str) -> str:
    credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {credentials}"


# ── Auth disabled ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auth_disabled_allows_all_requests():
    settings = make_settings(enabled=False)
    app = make_app(settings)
    with patch("src.api.middleware.auth.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/protected")
    assert response.status_code == 200


# ── Unprotected routes ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_bypasses_auth():
    settings = make_settings(enabled=True)
    app = make_app(settings)
    with patch("src.api.middleware.auth.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_docs_bypasses_auth():
    settings = make_settings(enabled=True)
    app = make_app(settings)
    with patch("src.api.middleware.auth.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/docs")
    assert response.status_code == 200


# ── Auth required ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_missing_auth_header_returns_401():
    settings = make_settings(enabled=True)
    app = make_app(settings)
    with patch("src.api.middleware.auth.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/protected")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


@pytest.mark.asyncio
async def test_wrong_credentials_returns_401():
    settings = make_settings(enabled=True)
    app = make_app(settings)
    with patch("src.api.middleware.auth.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/protected",
                headers={"Authorization": basic_auth_header("wrong", "credentials")}
            )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_correct_credentials_returns_200():
    settings = make_settings(enabled=True)
    app = make_app(settings)
    with patch("src.api.middleware.auth.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/protected",
                headers={"Authorization": basic_auth_header("testuser", "testpass")}
            )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_malformed_base64_returns_401():
    settings = make_settings(enabled=True)
    app = make_app(settings)
    with patch("src.api.middleware.auth.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/protected",
                headers={"Authorization": "Basic not-valid-base64!!!"}
            )
    assert response.status_code == 401