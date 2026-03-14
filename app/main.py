"""
Main entry point for the News Search API application.

This module provides the FastAPI application setup and server startup logic.
All business logic has been refactored into separate modules for maintainability.
"""

import os
import signal
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles

from .doc_store import _mongo_manager
from .logging_config import get_logger
from .factories import check_port_availability, get_fallback_port
from .middleware import get_server_config, setup_app_configuration
from .routes import (
    crawler_router,
    health_router,
    qa_router,
    search_router,
    summary_router,
    tagging_router,
)
from .session import session_manager, get_session_data

# =============================================================================
# APPLICATION INITIALIZATION
# =============================================================================

logger = get_logger(__name__)

# Create the FastAPI application
app = setup_app_configuration()

# Include all routers
app.include_router(health_router)
app.include_router(search_router)
app.include_router(crawler_router)
app.include_router(tagging_router)
app.include_router(summary_router)
app.include_router(qa_router)

# =============================================================================
# STATIC FILES
# =============================================================================

project_root = Path(__file__).parent.parent
static_dir = project_root / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def get_url_title_mapping(session_id: str) -> dict:
    """Get URL to title mapping from session search results."""
    session_data = get_session_data(session_id)
    search_results = session_data.get("search_results", [])
    return {
        result["url"]: result["title"]
        for result in search_results
        if "url" in result and "title" in result
    }


# =============================================================================
# MAIN EXECUTION
# =============================================================================

if __name__ == "__main__":

    def signal_handler(signum, frame):
        """Handle graceful shutdown on SIGINT/SIGTERM."""
        try:
            session_manager.cleanup_expired_sessions()
            _mongo_manager.close()
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
        finally:
            os._exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal_handler)

    config = get_server_config()
    preferred_port = config["port"]
    if not check_port_availability(preferred_port):
        config["port"] = get_fallback_port(preferred_port)

    run_args = {
        "app": "app.main:app",
        "host": config["host"],
        "port": config["port"],
        "reload": config["reload"],
        "timeout_keep_alive": config.get("timeout_keep_alive", 5),
        "timeout_graceful_shutdown": config.get("timeout_graceful_shutdown", 30),
        "limit_concurrency": config.get("limit_concurrency", 1000),
        "limit_max_requests": config.get("limit_max_requests", 10000),
        "access_log": config.get("reload", False),
    }

    # SSL configuration
    ssl_keyfile = config.get("ssl_keyfile")
    ssl_certfile = config.get("ssl_certfile")
    project_root = Path(__file__).parent.parent
    default_ssl_dir = project_root / "config" / "ssl"

    if ssl_keyfile and not os.path.isabs(ssl_keyfile):
        ssl_keyfile = str(default_ssl_dir / ssl_keyfile)
    elif not ssl_keyfile and (default_ssl_dir / "key.pem").exists():
        ssl_keyfile = str(default_ssl_dir / "key.pem")

    if ssl_certfile and not os.path.isabs(ssl_certfile):
        ssl_certfile = str(default_ssl_dir / ssl_certfile)
    elif not ssl_certfile and (default_ssl_dir / "cert.pem").exists():
        ssl_certfile = str(default_ssl_dir / "cert.pem")

    if (
        ssl_keyfile
        and ssl_certfile
        and os.path.exists(ssl_keyfile)
        and os.path.exists(ssl_certfile)
    ):
        run_args["ssl_keyfile"] = ssl_keyfile
        run_args["ssl_certfile"] = ssl_certfile
        logger.info(
            f"Starting HTTPS server on https://{config['host']}:{config['port']}"
        )
    else:
        logger.info(f"Starting HTTP server on http://{config['host']}:{config['port']}")

    uvicorn.run(**run_args)