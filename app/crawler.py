"""
Web crawler implementations for document retrieval.

This module provides multiple crawler implementations:
- ApifyCrawler: Uses Apify platform for web scraping
- Crawl4AICrawler: Uses Crawl4AI library for web scraping

Usage:
    # Using Apify crawler
    apify_crawler = ApifyCrawler()
    docs = await apify_crawler.get(urls, crawler_type="cheerio")

    # Using Crawl4AI crawler
    crawl4ai_crawler = Crawl4AICrawler(verbose=True)
    docs = await crawl4ai_crawler.get(urls)

    # Using factory function
    crawler = create_crawler("crawl4ai", verbose=True)
    docs = await crawler.get(urls)
"""

import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import List, Literal, Optional

from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
from dotenv import load_dotenv
from langchain_apify import ApifyWrapper
from langchain_core.documents import Document

load_dotenv()

# Type alias for crawler types
CrawlerType = Literal[
    "cheerio", "playwright:chrome", "playwright:firefox", "playwright:adaptive"
]

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class Crawler(ABC):
    """
    Abstract base class for web crawlers that retrieve documents from URLs.

    This class provides a common interface for different web crawling implementations,
    defining the basic structure and required methods for document retrieval.
    """

    def __init__(self) -> None:
        """Initialize the crawler instance."""
        super().__init__()

    @abstractmethod
    async def get(self, urls: List[str]) -> List[Document]:
        """Retrieve documents from the given URLs.

        Args:
            urls: List of URLs to crawl

        Returns:
            List of Document objects containing the crawled content

        Raises:
            NotImplementedError: This method must be implemented by subclasses
        """
        raise NotImplementedError


class ApifyCrawler(Crawler):
    """
    Crawler implementation using the Apify platform for web scraping.

    This class provides document retrieval functionality using Apify's
    website content crawler with configurable scraping parameters.
    """

    def __init__(self, client: Optional[ApifyWrapper] = None) -> None:
        """Initialize the Apify crawler with optional client.

        Args:
            client: Optional ApifyWrapper client instance. If None, a new client is created.
        """
        super().__init__()
        self.client = client or ApifyWrapper()

    async def get(
        self, urls: List[str], crawler_type: CrawlerType = "cheerio"
    ) -> List[Document]:
        """Retrieve documents from URLs using the Apify website content crawler.

        Args:
            urls: List of URLs to crawl
            crawler_type: Type of crawler to use. Options:
                - "cheerio": Fast, lightweight server-side DOM manipulation (default)
                - "playwright:chrome": Chrome browser automation with JavaScript support
                - "playwright:firefox": Firefox browser automation with JavaScript support
                - "playwright:adaptive": Automatically chooses between Cheerio and Playwright

        Returns:
            List of Document objects containing the crawled content

        Raises:
            ValueError: If an invalid crawler_type is provided
            Exception: If the Apify API call fails
        """
        # Validate crawler_type
        valid_types = [
            "cheerio",
            "playwright:chrome",
            "playwright:firefox",
            "playwright:adaptive",
        ]
        if crawler_type not in valid_types:
            raise ValueError(
                f"Invalid crawler_type '{crawler_type}'. Must be one of: {valid_types}"
            )

        try:
            logger.info(f"Starting crawl with crawler type: {crawler_type}")

            loader = await self.client.acall_actor(
                actor_id="apify/website-content-crawler",
                run_input={
                    "startUrls": [{"url": url} for url in urls],
                    "crawlerType": crawler_type,
                    "maxCrawlDepth": 0,
                    "useSitemaps": False,
                    "respectRobotsTxtFile": True,
                    "maxConcurrency": 10,
                    "maxSessionRotations": 10,
                    "maxRequestRetries": 1,
                    "requestTimeoutSecs": 30,
                    "dynamicContentWaitSecs": 2,
                    "proxyConfiguration": {
                        "useApifyProxy": True,
                    },
                    "keepElementsCssSelector": "article, main, .content, .article, .post, .entry",
                    "removeElementsCssSelector": """nav, footer, script, style, noscript, svg, 
                        img[src^='data:'], iframe, embed, object,
                        .advertisement, .ads, .social-share, .comments,
                        [role="alert"], [role="banner"], [role="dialog"], 
                        [role="alertdialog"], [role="region"][aria-label*="skip" i],
                        [aria-modal="true"], .cookie-banner, .newsletter""",
                    "blockMedia": True,
                    "clickElementsCssSelector": '[aria-expanded="false"]',
                },
                dataset_mapping_function=lambda item: Document(
                    page_content=item["text"] or "",
                    metadata={"source": item["url"]},
                ),
            )

            documents = loader.load()

            # Filter to only return documents with status code 200
            filtered_documents = []
            for doc in documents:
                # Check if document has valid content and assume 200 status for Apify
                # Apify doesn't provide status codes directly, so we filter by content presence
                if doc.page_content and doc.page_content.strip():
                    filtered_documents.append(doc)
                else:
                    logger.info(
                        f"Filtered out document from {doc.metadata.get('source', 'unknown')} - no content"
                    )

            logger.info(
                f"Successfully crawled {len(filtered_documents)} documents with valid content using {crawler_type}"
            )
            return filtered_documents

        except Exception as e:
            logger.error(
                f"Apify API call failed with crawler type '{crawler_type}': {str(e)}"
            )
            raise


class Crawl4AICrawler(Crawler):
    """
    Crawler implementation using the Crawl4AI library for web scraping.

    This class provides document retrieval functionality using Crawl4AI's
    AsyncWebCrawler with configurable browser and crawling parameters.
    """

    def __init__(
        self,
        browser_config: Optional[BrowserConfig] = None,
        run_config: Optional[CrawlerRunConfig] = None,
        verbose: bool = False,
    ) -> None:
        """Initialize the Crawl4AI crawler with optional configurations.

        Args:
            browser_config: Optional BrowserConfig instance for browser settings
            run_config: Optional CrawlerRunConfig instance for crawling settings
            verbose: Whether to enable verbose logging
        """
        super().__init__()

        # Initialize configurations - use default settings like working test.py
        self.browser_config = browser_config
        self.run_config = run_config

    async def get(self, urls: List[str]) -> List[Document]:
        """Retrieve documents from URLs using Crawl4AI AsyncWebCrawler.

        Args:
            urls: List of URLs to crawl

        Returns:
            List of Document objects containing the crawled content

        Raises:
            Exception: If the crawl operation fails
        """
        documents = []

        try:
            logger.info(f"Starting Crawl4AI crawl for {len(urls)} URLs")

            # Use the exact same approach as working test.py
            crawler_kwargs = {}
            if self.browser_config:
                crawler_kwargs["config"] = self.browser_config

            async with AsyncWebCrawler(**crawler_kwargs) as crawler:
                for url in urls:
                    try:
                        logger.info(f"Crawling URL: {url}")

                        # Use config only if provided, otherwise use defaults like test.py
                        run_kwargs = {"url": url}
                        if self.run_config:
                            run_kwargs["config"] = self.run_config

                        result = await crawler.arun(**run_kwargs)

                        if result.success and result.status_code == 200:
                            # Use raw markdown like in the working test.py
                            content = result.markdown or ""

                            # Only add documents with actual content
                            if content.strip():
                                # Create Document with content and metadata
                                doc = Document(
                                    page_content=content,
                                    metadata={
                                        "source": url,
                                        "status_code": result.status_code,
                                        "title": getattr(result, "title", ""),
                                        "description": getattr(
                                            result, "description", ""
                                        ),
                                        "keywords": getattr(result, "keywords", []),
                                        "language": getattr(result, "language", ""),
                                        "crawler": "crawl4ai",
                                    },
                                )
                                documents.append(doc)
                                logger.info(
                                    f"Successfully crawled {url} - {len(content)} characters (status: {result.status_code})"
                                )
                            else:
                                logger.info(f"Filtered out {url} - no content")
                        else:
                            status_msg = (
                                f"status: {result.status_code}"
                                if hasattr(result, "status_code")
                                else "unknown status"
                            )
                            logger.info(f"Filtered out {url} - {status_msg}")

                    except Exception as e:
                        logger.error(f"Exception while crawling {url}: {str(e)}")
                        # Don't add failed documents when filtering for 200 status only

            logger.info(
                f"Completed Crawl4AI crawl - {len(documents)} documents processed"
            )
            return documents

        except Exception as e:
            logger.error(f"Crawl4AI crawler failed: {str(e)}")
            raise

    async def get_with_custom_config(
        self,
        urls: List[str],
        browser_config: Optional[BrowserConfig] = None,
        run_config: Optional[CrawlerRunConfig] = None,
    ) -> List[Document]:
        """Retrieve documents with custom configurations for this specific crawl.

        Args:
            urls: List of URLs to crawl
            browser_config: Custom browser configuration for this crawl
            run_config: Custom run configuration for this crawl

        Returns:
            List of Document objects containing the crawled content
        """
        # Use provided configs or fall back to instance configs
        browser_cfg = browser_config or self.browser_config
        run_cfg = run_config or self.run_config

        documents = []

        try:
            logger.info(
                f"Starting Crawl4AI crawl with custom config for {len(urls)} URLs"
            )

            # Use configs only if provided
            crawler_kwargs = {}
            if browser_cfg:
                crawler_kwargs["config"] = browser_cfg

            async with AsyncWebCrawler(**crawler_kwargs) as crawler:
                for url in urls:
                    try:
                        run_kwargs = {"url": url}
                        if run_cfg:
                            run_kwargs["config"] = run_cfg

                        result = await crawler.arun(**run_kwargs)

                        if result.success:
                            content = result.markdown or ""

                            # Only add documents with actual content
                            if content.strip():
                                doc = Document(
                                    page_content=content,
                                    metadata={
                                        "source": url,
                                        "status_code": result.status_code,
                                        "title": getattr(result, "title", ""),
                                        "description": getattr(
                                            result, "description", ""
                                        ),
                                        "crawler": "crawl4ai",
                                    },
                                )
                                documents.append(doc)
                            else:
                                logger.info(
                                    f"Filtered out {url} - no content despite 200 status"
                                )
                        else:
                            status_msg = (
                                f"status: {result.status_code}"
                                if hasattr(result, "status_code")
                                else "unknown status"
                            )
                            logger.info(
                                f"Filtered out {url} - {status_msg} (only accepting 200)"
                            )

                    except Exception as e:
                        logger.error(f"Exception while crawling {url}: {str(e)}")
                        # Don't add failed documents when filtering for 200 status only

            return documents

        except Exception as e:
            logger.error(f"Crawl4AI crawler with custom config failed: {str(e)}")
            raise


def create_crawler(crawler_type: str = "apify", **kwargs) -> Crawler:
    """Factory function to create different types of crawlers.

    Args:
        crawler_type: Type of crawler to create ("apify" or "crawl4ai")
        **kwargs: Additional arguments to pass to the crawler constructor

    Returns:
        Crawler instance

    Raises:
        ValueError: If invalid crawler_type is provided
    """
    if crawler_type.lower() == "apify":
        return ApifyCrawler(**kwargs)
    elif crawler_type.lower() == "crawl4ai":
        return Crawl4AICrawler(**kwargs)
    else:
        raise ValueError(
            f"Unknown crawler type: {crawler_type}. Supported types: 'apify', 'crawl4ai'"
        )


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def main():
        """Main function to demonstrate the crawler functionality."""
        apify_crawler = ApifyCrawler()

        # Test with different crawler types
        test_urls = [
            "https://www.investopedia.com/articles/investing/020116/theranos-fallen-unicorn.asp",
            "https://www.ebsco.com/research-starters/technology/theranos",
        ]

        # Test with default cheerio crawler
        print("Testing with Apify cheerio crawler...")
        docs_cheerio = await apify_crawler.get(test_urls, crawler_type="cheerio")
        print(f"Apify cheerio crawler retrieved {len(docs_cheerio)} documents")
        # Debug output - uncomment for testing
        for doc in docs_cheerio:
            print(doc.page_content, doc.metadata.get("source", ""))

        # Test with playwright chrome crawler (uncomment to test)
        print("Testing with playwright:chrome crawler...")
        docs_chrome = await apify_crawler.get(
            test_urls, crawler_type="playwright:chrome"
        )
        print(f"Playwright Chrome crawler retrieved {len(docs_chrome)} documents")
        # Debug output - uncomment for testing
        for doc in docs_chrome:
            print(doc.page_content, doc.metadata.get("source", ""))

        # Test Crawl4AI crawler
        print("\nTesting with Crawl4AI crawler...")
        crawl4ai_crawler = Crawl4AICrawler()
        docs_crawl4ai = await crawl4ai_crawler.get(test_urls)
        print(f"Crawl4AI crawler retrieved {len(docs_crawl4ai)} documents")

        # Show sample content from Crawl4AI
        for i, doc in enumerate(docs_crawl4ai):
            print(
                f"\nCrawl4AI Doc {i + 1} from {doc.metadata.get('source', 'unknown')}:"
            )
            print(f"Content length: {len(doc.page_content)}")
            print(f"Status code: {doc.metadata.get('status_code', 'unknown')}")
            if doc.page_content:
                print(f"Content preview: {doc.page_content[:200]}...")
            else:
                print("No content retrieved")
                if "error" in doc.metadata:
                    print(f"Error: {doc.metadata['error']}")
            print(f"Full metadata: {doc.metadata}")

    asyncio.run(main())
