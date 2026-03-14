"""
Session management for the application.

This module provides thread-safe session management with automatic cleanup
and cookie handling for HTTP responses.
"""

import hashlib
import os
import secrets
import threading
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Response
from fastapi.responses import JSONResponse

from .config import DEFAULT_SESSION_TIMEOUT_HOURS
from .logging_config import get_logger

__all__ = [
    # Session manager
    "session_manager",
    "ThreadSafeSessionManager",
    # Cookie configuration
    "COOKIE_SAMESITE",
    "COOKIE_SECURE",
    "COOKIE_DOMAIN",
    "SESSION_MAX_AGE",
    "SESSION_SECRET_KEY",
    # Session helpers
    "generate_session_id",
    "get_session_data",
    "update_session_data",
    "set_session_cookie",
    "create_json_response_with_cookies",
]

logger = get_logger(__name__)

# =============================================================================
# COOKIE AND SESSION CONFIGURATION
# =============================================================================

COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "Lax")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "true").lower() == "true"
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN", "")
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", "86400"))
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", secrets.token_urlsafe(32))


# =============================================================================
# THREAD-SAFE SESSION MANAGER
# =============================================================================


class ThreadSafeSessionManager:
    """Thread-safe session management with automatic cleanup."""

    def __init__(self, timeout_hours: int = DEFAULT_SESSION_TIMEOUT_HOURS):
        self._sessions = {}
        self._lock = threading.RLock()
        self._timeout_hours = timeout_hours

    def create_session(self, session_id: str) -> dict:
        """Create a new session with thread-safe initialization."""
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {
                    "created_at": datetime.now(),
                    "last_accessed": datetime.now(),
                    "search_results": [],
                    "web_contents": {},
                    "user_context": {},
                }
            return self._sessions[session_id]

    def get_session(self, session_id: str) -> dict:
        """Get session data with thread-safe access."""
        with self._lock:
            session = self._sessions.get(session_id, {})
            if session:
                session["last_accessed"] = datetime.now()
            return session.copy()

    def update_session(self, session_id: str, key: str, value) -> None:
        """Update session data with thread-safe access."""
        with self._lock:
            if session_id not in self._sessions:
                self.create_session(session_id)
            self._sessions[session_id][key] = value
            self._sessions[session_id]["last_accessed"] = datetime.now()

    def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions and return count of removed sessions."""
        cutoff_time = datetime.now() - timedelta(hours=self._timeout_hours)
        with self._lock:
            expired_sessions = [
                session_id
                for session_id, session_data in self._sessions.items()
                if session_data.get("last_accessed", datetime.now()) < cutoff_time
            ]
            for session_id in expired_sessions:
                del self._sessions[session_id]
            return len(expired_sessions)

    def get_session_count(self) -> int:
        """Get total number of active sessions."""
        with self._lock:
            return len(self._sessions)

    def remove_session(self, session_id: str) -> bool:
        """Remove a specific session."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False


# Global session manager instance
session_manager = ThreadSafeSessionManager()


# =============================================================================
# SESSION HELPER FUNCTIONS
# =============================================================================


def generate_session_id(ip: str, user_agent: str = "") -> str:
    """Generate session ID based on client info and timestamp."""
    timestamp = str(datetime.now().timestamp())
    content = f"{ip}_{user_agent}_{timestamp}"
    return hashlib.md5(content.encode()).hexdigest()


def get_session_data(session_id: str) -> dict:
    """Get session data for given session ID."""
    return session_manager.get_session(session_id)


def update_session_data(session_id: str, key: str, value) -> None:
    """Update session data for given session ID and key."""
    session_manager.update_session(session_id, key, value)


def set_session_cookie(
    response: Response, session_id: str, max_age: int = SESSION_MAX_AGE
):
    """Set session cookie with proper SameSite and Secure policies."""
    cookie_kwargs = {
        "key": "session_id",
        "value": session_id,
        "max_age": max_age,
        "httponly": True,
        "samesite": COOKIE_SAMESITE,
        "secure": COOKIE_SECURE,
    }
    if COOKIE_DOMAIN:
        cookie_kwargs["domain"] = COOKIE_DOMAIN
    response.set_cookie(**cookie_kwargs)
    return response


def create_json_response_with_cookies(
    data: dict, session_id: Optional[str] = None
) -> JSONResponse:
    """Create a JSON response with proper cookie settings."""
    response = JSONResponse(content=data)
    if session_id:
        set_session_cookie(response, session_id)
    return response