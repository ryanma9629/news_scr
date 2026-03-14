"""
Middleware and application configuration.

This module provides middleware components, lifespan management,
and application configuration for the FastAPI application.
"""

import os
from contextlib import asynccontextmanager
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.middleware.sessions import SessionMiddleware

from .doc_store import _mongo_manager
from .logging_config import get_logger, setup_logging
from .session import (
    SESSION_MAX_AGE,
    SESSION_SECRET_KEY,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    COOKIE_DOMAIN,
    session_manager,
)

__all__ = [
    "ALLOW_IFRAME_EMBEDDING",
    "IFRAME_ALLOWED_ORIGINS",
    "VI_DEPLOY",
    "lifespan",
    "get_cors_origins",
    "setup_app_configuration",
    "get_server_config",
]

# Load environment variables
load_dotenv()

logger = get_logger(__name__)

# =============================================================================
# CONFIGURATION CONSTANTS
# =============================================================================

VI_DEPLOY = os.getenv("VI_DEPLOY", "false").lower() == "true"

# IFRAME configuration
ALLOW_IFRAME_EMBEDDING = os.getenv("ALLOW_IFRAME_EMBEDDING", "false").lower() == "true"
IFRAME_ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("IFRAME_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]


# =============================================================================
# LIFESPAN MANAGEMENT
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    # Initialize centralized logging configuration
    setup_logging(force=True)
    session_manager.cleanup_expired_sessions()
    yield
    try:
        _mongo_manager.close()
    except Exception as e:
        logger.error(f"Error closing MongoDB connections: {e}")


# =============================================================================
# CORS CONFIGURATION
# =============================================================================


def get_cors_origins() -> List[str]:
    """Get CORS origins configuration."""
    cors_origins = [
        "https://localhost:8280",
        "https://127.0.0.1:8280",
        "http://localhost:8280",
        "http://127.0.0.1:8280",
        "https://localhost",
        "https://127.0.0.1",
        "http://localhost",
        "http://127.0.0.1",
        "http://sasserver.demo.sas.com",
        "https://sasserver.demo.sas.com",
        "http://sasserver",
        "https://sasserver",
    ]
    if ALLOW_IFRAME_EMBEDDING and IFRAME_ALLOWED_ORIGINS:
        if "*" in IFRAME_ALLOWED_ORIGINS:
            cors_origins = ["*"]
        else:
            cors_origins.extend(IFRAME_ALLOWED_ORIGINS)
    return cors_origins


# =============================================================================
# APP CONFIGURATION
# =============================================================================


def setup_app_configuration() -> FastAPI:
    """Setup FastAPI app with middleware and static files."""
    app = FastAPI(title="News Search API", version="1.0.0", lifespan=lifespan)

    # Session middleware
    app.add_middleware(
        SessionMiddleware,
        secret_key=SESSION_SECRET_KEY,
        max_age=SESSION_MAX_AGE,
        same_site=COOKIE_SAMESITE.lower(),  # type: ignore
        https_only=COOKIE_SECURE,
        domain=COOKIE_DOMAIN if COOKIE_DOMAIN else None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    # Security headers middleware
    @app.middleware("http")
    async def add_security_headers(request: Request, call_next):
        """Add security headers including IFRAME and cookie policies."""
        response = await call_next(request)

        # IFRAME embedding headers
        if ALLOW_IFRAME_EMBEDDING:
            if "*" in IFRAME_ALLOWED_ORIGINS or not IFRAME_ALLOWED_ORIGINS:
                response.headers["X-Frame-Options"] = "ALLOWALL"
                response.headers["Content-Security-Policy"] = "frame-ancestors *"
            else:
                allowed_origins = " ".join(IFRAME_ALLOWED_ORIGINS)
                response.headers["Content-Security-Policy"] = (
                    f"frame-ancestors {allowed_origins}"
                )
        else:
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"

        # Additional security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response

    # Connection error handling middleware
    @app.middleware("http")
    async def connection_error_handler(request: Request, call_next):
        """Handle connection reset errors gracefully."""
        try:
            return await call_next(request)
        except ConnectionResetError:
            return Response(status_code=499, content="Client closed connection")
        except Exception as e:
            logger.error(f"Unexpected error handling request: {str(e)}")
            raise

    return app


# =============================================================================
# SERVER CONFIGURATION
# =============================================================================


def get_server_config() -> dict:
    """Get server configuration from environment or defaults."""
    return {
        "host": "0.0.0.0",
        "port": 8280,
        "reload": os.getenv("RELOAD", "false").lower() == "true",
        "ssl_keyfile": os.getenv("SSL_KEYFILE"),
        "ssl_certfile": os.getenv("SSL_CERTFILE"),
        "timeout_keep_alive": int(os.getenv("TIMEOUT_KEEP_ALIVE", "5")),
        "timeout_graceful_shutdown": int(os.getenv("TIMEOUT_GRACEFUL_SHUTDOWN", "30")),
        "limit_concurrency": int(os.getenv("LIMIT_CONCURRENCY", "1000")),
        "limit_max_requests": int(os.getenv("LIMIT_MAX_REQUESTS", "10000")),
    }