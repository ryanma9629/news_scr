"""
API route modules.

This package contains individual route modules for each API endpoint group.
"""

from .search import router as search_router
from .crawler import router as crawler_router
from .tagging import router as tagging_router
from .summary import router as summary_router
from .qa import router as qa_router
from .health import router as health_router

__all__ = [
    "search_router",
    "crawler_router",
    "tagging_router",
    "summary_router",
    "qa_router",
    "health_router",
]