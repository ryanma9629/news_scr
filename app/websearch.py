"""
Web search implementations for news article discovery.

This module provides abstract and concrete implementations for web search
functionality using various search providers like Google Serper and Tavily.
"""

__all__ = [
    "SearchResult",
    "WebSearch",
    "GoogleSerperNews",
    "TavilySearch",
    "LANGUAGE_MAPPINGS",
    "LOCATION_MAPPINGS",
]

import os
from abc import ABC, abstractmethod
from typing import List, Optional, TypedDict

import httpx
from dotenv import load_dotenv
from langchain_community.utilities.google_serper import GoogleSerperAPIWrapper

from .config import TAVILY_SEARCH_URL, TAVILY_DEFAULT_TIMEOUT, get_tavily_api_key
from .logging_config import get_logger

# Initialize logger using shared configuration
logger = get_logger(__name__)

# Load environment variables
load_dotenv()


class SearchResult(TypedDict):
    """Type definition for search result structure."""

    url: str
    title: str


LANGUAGE_MAPPINGS = {
    "google": {
        "Simplified Chinese": "zh-cn",
        "Traditional Chinese": "zh-tw",
        "English": "en",
        "Japanese": "ja",
    },
    "tavily": {},  # No language support
}

LOCATION_MAPPINGS = {
    "google": {
        "China": "cn",
        "Hong Kong": "hk",
        "United States": "us",
        "Japan": "jp",
    },
    "tavily": {},  # No location support
}


class WebSearch(ABC):
    """
    Abstract base class for web search implementations.

    This class provides a common interface for different web search providers,
    defining the basic structure and required methods for search operations.
    """

    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        """
        Initialize web search with language and location settings.

        Args:
            lang: Language for search results
            location: Location for search results (optional)
        """
        self.lang = lang
        self.location = location

    def _get_language_mapping(self, provider: str) -> str:
        """Get language mapping for the specified provider"""
        return LANGUAGE_MAPPINGS.get(provider, {}).get(self.lang, "en")

    def _get_location_mapping(self, provider: str) -> str:
        """Get location mapping for the specified provider"""
        if self.location:
            return LOCATION_MAPPINGS.get(provider, {}).get(
                self.location, "us" if provider == "google" else "en-US"
            )
        return "us" if provider == "google" else "en-US"

    def _validate_inputs(self, keywords: str, max_results: int) -> None:
        """Validate input parameters"""
        if not keywords or not keywords.strip():
            raise ValueError("Keywords cannot be empty")
        if max_results <= 0:
            raise ValueError("max_results must be positive")

    def _create_search_result(self, items: List[dict]) -> List[SearchResult]:
        """Create standardized search results"""
        return [{"url": item["link"], "title": item["title"]} for item in items]

    @abstractmethod
    def search(
        self, keywords: str, max_results: int, **kwargs
    ) -> Optional[List[SearchResult]]:
        """
        Abstract method for performing web search.

        Args:
            keywords: Search keywords
            max_results: Maximum number of results to return
            **kwargs: Additional search parameters

        Returns:
            List of search results or None if search fails

        Raises:
            NotImplementedError: Must be implemented by subclasses
        """
        raise NotImplementedError

    async def asearch(
        self, keywords: str, max_results: int, **kwargs
    ) -> Optional[List[SearchResult]]:
        """
        Async version of search method.

        Default implementation calls the sync version in a thread pool.
        Subclasses should override this for native async support.

        Args:
            keywords: Search keywords
            max_results: Maximum number of results to return
            **kwargs: Additional search parameters

        Returns:
            List of search results or None if search fails
        """
        import asyncio
        return await asyncio.to_thread(self.search, keywords, max_results, **kwargs)


class GoogleSerperNews(WebSearch):
    """
    Google Serper News Search implementation.

    This class provides news search functionality using the Google Serper API,
    with support for language and location-based filtering.
    """

    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        """
        Initialize Google Serper News search.

        Args:
            lang: Language for search results
            location: Location for search results (optional)
        """
        super().__init__(lang, location)

    def _language_to_hl(self) -> str:
        """Convert language to Google's hl parameter format"""
        return self._get_language_mapping("google")

    def _location_to_gl(self) -> str:
        """Convert location to Google's gl parameter format"""
        return self._get_location_mapping("google")

    def search(
        self, keywords: str, max_results: int = 5, **kwargs
    ) -> Optional[List[SearchResult]]:
        """
        Search for news using Google Serper API.

        Args:
            keywords: Search keywords
            max_results: Maximum number of results to return
            **kwargs: Additional search parameters

        Returns:
            List of search results or None if search fails
        """
        try:
            self._validate_inputs(keywords, max_results)

            hl = self._language_to_hl()
            gl = self._location_to_gl()

            logger.info(
                f"Searching Google with keywords: {keywords}, lang: {hl}, location: {gl}"
            )

            search = GoogleSerperAPIWrapper(
                k=max_results, type="news", gl=gl, hl=hl, **kwargs
            )
            search_results = search.results(keywords).get("news")

            if search_results:
                # Ensure we don't return more results than requested
                limited_results = search_results[:max_results]
                logger.info(
                    f"Found {len(search_results)} results from Google, returning {len(limited_results)}"
                )
                return self._create_search_result(limited_results)
            else:
                logger.warning("No results found from Google")
                return None

        except ValueError as e:
            logger.error(f"Google search input validation failed: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Google search failed: {str(e)}")
            return None


class TavilySearch(WebSearch):
    """
    Tavily Search implementation.

    This class provides search functionality using the Tavily Search API,
    optimized for AI applications with news-focused results.
    Note: Tavily does not support explicit language or location filtering.
    """

    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        """
        Initialize Tavily search.

        Args:
            lang: Language for search results (not used by Tavily)
            location: Location for search results (not used by Tavily)
        """
        super().__init__(lang, location)

    def search(
        self, keywords: str, max_results: int = 10, **kwargs
    ) -> Optional[List[SearchResult]]:
        """
        Search using Tavily Search API (synchronous wrapper).

        Note: In async contexts (like FastAPI), prefer using asearch() directly.
        This method uses asyncio.run() which creates a new event loop.

        Args:
            keywords: Search keywords
            max_results: Maximum number of results to return
            **kwargs: Additional search parameters

        Returns:
            List of search results or None if search fails

        Raises:
            RuntimeError: If called from an async context (use asearch() instead)
        """
        import asyncio

        # asyncio.run() handles event loop creation and cleanup properly
        # It will raise RuntimeError if called from an async context
        return asyncio.run(self.asearch(keywords, max_results, **kwargs))

    async def asearch(
        self, keywords: str, max_results: int = 10, **kwargs
    ) -> Optional[List[SearchResult]]:
        """
        Search using Tavily Search API (async native).

        Args:
            keywords: Search keywords
            max_results: Maximum number of results to return
            **kwargs: Additional search parameters

        Returns:
            List of search results or None if search fails
        """
        try:
            self._validate_inputs(keywords, max_results)

            tavily_key = get_tavily_api_key()

            logger.info(f"Searching Tavily with keywords: {keywords}")

            async with httpx.AsyncClient(timeout=TAVILY_DEFAULT_TIMEOUT) as client:
                response = await client.post(
                    TAVILY_SEARCH_URL,
                    json={
                        "query": keywords,
                        "max_results": max_results,
                        "topic": "general",
                        "search_depth": "advanced",
                    },
                    headers={
                        "Authorization": f"Bearer {tavily_key}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                data = response.json()

            results = data.get("results", [])
            if results:
                # Transform to our SearchResult format
                search_results = []
                for item in results:
                    if "url" in item and "title" in item:
                        search_results.append({
                            "url": item["url"],
                            "title": item["title"],
                        })
                # Ensure we don't return more results than requested
                limited_results = search_results[:max_results]
                logger.info(
                    f"Found {len(search_results)} results from Tavily, returning {len(limited_results)}"
                )
                return limited_results
            else:
                logger.warning("No results found from Tavily")
                return None

        except httpx.HTTPStatusError as e:
            logger.error(f"Tavily API error: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Tavily search failed: {str(e)}")
            return None