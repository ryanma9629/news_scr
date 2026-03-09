"""
Web search implementations for news article discovery.

This module provides abstract and concrete implementations for web search
functionality using various search providers like Google Serper, Bing,
Brave Search, and Tavily.
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import List, Optional, TypedDict

import httpx
from dotenv import load_dotenv
from langchain_community.utilities import BingSearchAPIWrapper
from langchain_community.utilities.google_serper import GoogleSerperAPIWrapper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Initialize logger
logger = logging.getLogger(__name__)

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
    "bing": {
        "Simplified Chinese": "zh-hans",
        "Traditional Chinese": "zh-hant",
        "English": "en",
        "Japanese": "ja",
    },
    "brave": {
        "Simplified Chinese": "zh-hans",
        "Traditional Chinese": "zh-hant",
        "English": "en",
        "Japanese": "ja",
    },
    "tavily": {
        "Simplified Chinese": "zh",
        "Traditional Chinese": "zh-tw",
        "English": "en",
        "Japanese": "ja",
    },
}

LOCATION_MAPPINGS = {
    "google": {
        "China": "cn",
        "Hong Kong": "hk",
        "United States": "us",
        "Japan": "jp",
    },
    "bing": {
        "China": "zh-CN",
        "Hong Kong": "zh-HK",
        "Taiwan": "zh-TW",
        "United States": "en-US",
        "Japan": "ja-JP",
    },
    "brave": {
        "China": "zh-cn",
        "Hong Kong": "zh-hk",
        "Taiwan": "zh-tw",
        "United States": "en-us",
        "Japan": "ja-jp",
    },
    "tavily": {
        "China": "CN",
        "Hong Kong": "HK",
        "Taiwan": "TW",
        "United States": "US",
        "Japan": "JP",
    },
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


class BingSearch(WebSearch):
    """
    Bing Search implementation.

    This class provides search functionality using the Bing Search API,
    with support for language and market-based filtering.
    """

    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        """
        Initialize Bing search.

        Args:
            lang: Language for search results
            location: Location for search results (optional)
        """
        super().__init__(lang, location)

    def _language_to_setlang(self) -> str:
        """Convert language to Bing's setLang parameter format"""
        return self._get_language_mapping("bing")

    def _location_to_mkt(self) -> str:
        """Convert location to Bing's mkt parameter format"""
        return self._get_location_mapping("bing")

    def search(
        self, keywords: str, max_results: int = 10, **kwargs
    ) -> Optional[List[SearchResult]]:
        """
        Search using Bing Search API.

        Args:
            keywords: Search keywords
            max_results: Maximum number of results to return
            **kwargs: Additional search parameters

        Returns:
            List of search results or None if search fails
        """
        try:
            self._validate_inputs(keywords, max_results)

            mkt = self._location_to_mkt()
            setlang = self._language_to_setlang()

            logger.info(
                f"Searching Bing with keywords: {keywords}, lang: {setlang}, market: {mkt}"
            )

            search_kwargs = {
                "mkt": mkt,
                "setLang": setlang,
                **kwargs,
            }

            bing_key = os.getenv("BING_SUBSCRIPTION_KEY")
            if not bing_key:
                raise ValueError("BING_SUBSCRIPTION_KEY environment variable not set")

            search = BingSearchAPIWrapper(
                bing_subscription_key=bing_key,
                bing_search_url=os.getenv(
                    "BING_SEARCH_URL", "https://api.bing.microsoft.com/v7.0/search"
                ),
                k=max_results,
                search_kwargs=search_kwargs,
            )
            search_results = search.results(keywords, num_results=max_results)

            if search_results:
                # Ensure we don't return more results than requested
                limited_results = search_results[:max_results]
                logger.info(
                    f"Found {len(search_results)} results from Bing, returning {len(limited_results)}"
                )
                return self._create_search_result(limited_results)
            else:
                logger.warning("No results found from Bing")
                return None

        except ValueError as e:
            logger.error(f"Bing search configuration error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Bing search failed: {str(e)}")
            return None


class BraveSearch(WebSearch):
    """
    Brave Search implementation.

    This class provides search functionality using the Brave Search API,
    with support for language and country-based filtering.
    """

    BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        """
        Initialize Brave search.

        Args:
            lang: Language for search results
            location: Location for search results (optional)
        """
        super().__init__(lang, location)

    def _language_to_search_lang(self) -> str:
        """Convert language to Brave's search_lang parameter format"""
        return self._get_language_mapping("brave")

    def _location_to_country(self) -> str:
        """Convert location to Brave's country parameter format"""
        return self._get_location_mapping("brave")

    def search(
        self, keywords: str, max_results: int = 10, **kwargs
    ) -> Optional[List[SearchResult]]:
        """
        Search using Brave Search API.

        Args:
            keywords: Search keywords
            max_results: Maximum number of results to return
            **kwargs: Additional search parameters

        Returns:
            List of search results or None if search fails
        """
        try:
            self._validate_inputs(keywords, max_results)

            brave_api_key = os.getenv("BRAVE_API_KEY")
            if not brave_api_key:
                raise ValueError("BRAVE_API_KEY environment variable not set")

            search_lang = self._language_to_search_lang()
            country = self._location_to_country()

            logger.info(
                f"Searching Brave with keywords: {keywords}, lang: {search_lang}, country: {country}"
            )

            headers = {
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": brave_api_key,
            }

            params = {
                "q": keywords,
                "count": max_results,
                "search_lang": search_lang,
                "country": country,
                "result_filter": "web",  # Focus on web results
                **kwargs,
            }

            with httpx.Client(timeout=30.0) as client:
                response = client.get(self.BRAVE_SEARCH_URL, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()

            # Parse Brave Search results
            web_results = data.get("web", {}).get("results", [])

            if web_results:
                results = []
                for item in web_results[:max_results]:
                    results.append({
                        "url": item.get("url", ""),
                        "title": item.get("title", ""),
                    })
                logger.info(
                    f"Found {len(web_results)} results from Brave, returning {len(results)}"
                )
                return results
            else:
                logger.warning("No results found from Brave")
                return None

        except ValueError as e:
            logger.error(f"Brave search configuration error: {str(e)}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"Brave search HTTP error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Brave search failed: {str(e)}")
            return None


class TavilySearch(WebSearch):
    """
    Tavily Search implementation.

    This class provides search functionality using the Tavily Search API,
    optimized for AI applications with comprehensive results.
    """

    TAVILY_SEARCH_URL = "https://api.tavily.com/search"

    def __init__(self, lang: str, location: Optional[str] = None) -> None:
        """
        Initialize Tavily search.

        Args:
            lang: Language for search results
            location: Location for search results (optional)
        """
        super().__init__(lang, location)

    def search(
        self, keywords: str, max_results: int = 10, **kwargs
    ) -> Optional[List[SearchResult]]:
        """
        Search using Tavily Search API.

        Args:
            keywords: Search keywords
            max_results: Maximum number of results to return
            **kwargs: Additional search parameters

        Returns:
            List of search results or None if search fails
        """
        try:
            self._validate_inputs(keywords, max_results)

            tavily_api_key = os.getenv("TAVILY_API_KEY")
            if not tavily_api_key:
                raise ValueError("TAVILY_API_KEY environment variable not set")

            logger.info(
                f"Searching Tavily with keywords: {keywords}"
            )

            headers = {
                "Content-Type": "application/json",
            }

            payload = {
                "api_key": tavily_api_key,
                "query": keywords,
                "max_results": max_results,
                "search_depth": "basic",  # Use "advanced" for more comprehensive results
                "include_answer": False,
                "include_raw_content": False,
                **kwargs,
            }

            with httpx.Client(timeout=30.0) as client:
                response = client.post(self.TAVILY_SEARCH_URL, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

            # Parse Tavily Search results
            results_data = data.get("results", [])

            if results_data:
                results = []
                for item in results_data[:max_results]:
                    results.append({
                        "url": item.get("url", ""),
                        "title": item.get("title", ""),
                    })
                logger.info(
                    f"Found {len(results_data)} results from Tavily, returning {len(results)}"
                )
                return results
            else:
                logger.warning("No results found from Tavily")
                return None

        except ValueError as e:
            logger.error(f"Tavily search configuration error: {str(e)}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"Tavily search HTTP error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Tavily search failed: {str(e)}")
            return None


if __name__ == "__main__":

    def main():
        """Main function for testing search functionality."""
        google_search = GoogleSerperNews(lang="English", location="United States")
        google_result = google_search.search("Theranos")
        # Debug output - uncomment for testing
        print("Google search result:", google_result)

        bing_search = BingSearch(lang="English", location="United States")
        bing_result = bing_search.search("Theranos")
        # Debug output - uncomment for testing
        print("Bing search result:", bing_result)

        brave_search = BraveSearch(lang="English", location="United States")
        brave_result = brave_search.search("Theranos")
        # Debug output - uncomment for testing
        print("Brave search result:", brave_result)

        tavily_search = TavilySearch(lang="English", location="United States")
        tavily_result = tavily_search.search("Theranos")
        # Debug output - uncomment for testing
        print("Tavily search result:", tavily_result)

        # Results available for testing
        _ = google_result, bing_result, brave_result, tavily_result

    main()
