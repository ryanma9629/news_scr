"""
Decorators for API endpoint handling.

This module provides decorators for session validation and error handling
across API endpoints.
"""

from functools import wraps

from fastapi import HTTPException

from .logging_config import get_logger
from .managers import ResponseManager
from .session import session_manager

__all__ = [
    "require_session",
    "handle_api_errors",
]

logger = get_logger(__name__)


def require_session(strict: bool = True):
    """Decorator to validate session requirement and cleanup expired sessions.

    Args:
        strict: If True, raises HTTPException when session_id is missing.
                If False, allows the endpoint to proceed without session.

    Returns:
        Decorator function that wraps the endpoint handler.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            session_manager.cleanup_expired_sessions()
            request = None
            for arg in args:
                if hasattr(arg, "session_id"):
                    request = arg
                    break
            if strict and (not request or not request.session_id):
                raise HTTPException(status_code=400, detail="Session ID is required")
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def handle_api_errors(response_class):
    """Decorator to handle common API errors and responses.

    Args:
        response_class: The Pydantic response model class to use for error responses.

    Returns:
        Decorator function that wraps the endpoint handler with error handling.
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException as he:
                # Re-raise HTTP exceptions
                raise he
            except Exception as e:
                logger.error(f"API error in {func.__name__}: {e}")
                # Extract request object to get URLs for error response
                request = None
                for arg in args:
                    if hasattr(arg, "urls"):
                        request = arg
                        break

                urls = getattr(request, "urls", []) if request else []
                return ResponseManager.create_error_response(
                    response_class, urls, f"System error: {e}"
                )

        return wrapper

    return decorator