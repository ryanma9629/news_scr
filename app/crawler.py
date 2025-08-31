"""
Web crawling implementations for content extraction.

This module provides abstract and concrete implementations for web crawling
functionality using various crawlers like Apify for document retrieval.
"""

import asyncio
import logging
import sys
from abc import ABC, abstractmethod
from typing import List, Optional, Literal

from dotenv import load_dotenv
from langchain_apify import ApifyWrapper
from langchain_core.documents import Document

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

# Type alias for crawler types
CrawlerType = Literal["cheerio", "playwright:chrome", "playwright:firefox", "playwright:adaptive"]


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

    async def get(self, urls: List[str], crawler_type: CrawlerType = "cheerio") -> List[Document]:
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
        valid_types = ["cheerio", "playwright:chrome", "playwright:firefox", "playwright:adaptive"]
        if crawler_type not in valid_types:
            raise ValueError(f"Invalid crawler_type '{crawler_type}'. Must be one of: {valid_types}")

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
            logger.info(f"Successfully crawled {len(documents)} documents using {crawler_type}")
            return documents
            
        except Exception as e:
            logger.error(f"Apify API call failed with crawler type '{crawler_type}': {str(e)}")
            raise



if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def main():
        """Main function to demonstrate the crawler functionality."""
        # Test with different crawler types
        test_urls = [
            "https://www.investopedia.com/articles/investing/020116/theranos-fallen-unicorn.asp",
            "https://www.ebsco.com/research-starters/technology/theranos",
            # "https://www.bloomberg.com/news/articles/2025-08-28/dell-raises-annual-forecasts-on-strong-demand-for-ai-servers"
        ]
        
        # Test Apify crawler
        print("Testing Apify crawler...")
        apify_crawler = ApifyCrawler()
        try:
            docs_apify = await apify_crawler.get(test_urls, crawler_type="cheerio")
            print(f"Apify crawler retrieved {len(docs_apify)} documents")
            
            # Debug output - uncomment for testing
            for doc in docs_apify:
                print(f"Source: {doc.metadata.get('source', '')}")
                print(f"Content preview: {doc.page_content[:1000]}...")
                print("---")
        except Exception as e:
            print(f"Apify crawler failed: {e}")

    asyncio.run(main())
